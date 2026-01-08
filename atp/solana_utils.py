"""
Solana helpers used by the ATP Gateway.

This module intentionally keeps Solana-specific logic isolated from the FastAPI app.

Security note:
- `verify_solana_transaction()` currently verifies *success* and that a transaction exists,
  but it does NOT parse instructions to prove the recipient + amount match expectations.
  For production-grade payment validation, you should parse the transaction and enforce:
  - payer == expected sender
  - recipient == configured treasury pubkey
  - amount == expected lamports / token amount
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger
from solana.rpc.async_api import AsyncClient as SolanaClient
from solana.rpc.types import TxOpts
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction as SoldersTransaction

from atp import config
from atp.schemas import PaymentToken


def _dbg_enabled() -> bool:
    return bool(getattr(config, "ATP_SOLANA_DEBUG", False))


def _dbg(msg: str, *args: Any) -> None:
    """Emit debug logs only when ATP_SOLANA_DEBUG=true."""
    if _dbg_enabled():
        logger.debug(msg, *args)


def _type_name(v: Any) -> str:
    try:
        return type(v).__name__
    except Exception:
        return "<unknown>"


def _as_dict(obj: Any) -> Any:
    """Best-effort conversion of solana-py response objects into plain dicts."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    # solana-py response objects may expose `.to_json()`
    to_json = getattr(obj, "to_json", None)
    if callable(to_json):
        try:
            return json.loads(to_json())
        except Exception:
            pass
    # fallback: try __dict__
    d = getattr(obj, "__dict__", None)
    return d if isinstance(d, dict) else obj


def _unwrap_get_transaction_response(
    resp: Any,
) -> Optional[Dict[str, Any]]:
    """Extract the transaction payload from various solana-py response shapes."""
    if resp is None:
        return None

    if isinstance(resp, dict):
        # classic JSON-RPC envelope: {"result": {...}} or newer: {"value": {...}}
        tx = resp.get("result") or resp.get("value")
        return tx if isinstance(tx, dict) else None

    value = getattr(resp, "value", None)
    if isinstance(value, dict):
        return value
    if value is not None:
        value_dict = _as_dict(value)
        return value_dict if isinstance(value_dict, dict) else None

    # some builds use `.result`
    result = getattr(resp, "result", None)
    if isinstance(result, dict):
        return result

    # last resort: dictify whole response and re-unwrap
    d = _as_dict(resp)
    if isinstance(d, dict):
        tx = d.get("result") or d.get("value")
        return tx if isinstance(tx, dict) else None
    return None


def _iter_instructions_json_parsed(
    tx: Dict[str, Any],
) -> Iterable[Dict[str, Any]]:
    """
    Iterate over instructions and inner instructions from a jsonParsed transaction payload.
    """
    try:
        message = (tx.get("transaction") or {}).get("message") or {}
        instructions = message.get("instructions") or []
        for ix in instructions:
            if isinstance(ix, dict):
                yield ix

        meta = tx.get("meta") or {}
        inner = meta.get("innerInstructions") or []
        for inner_entry in inner:
            if not isinstance(inner_entry, dict):
                continue
            for ix in inner_entry.get("instructions") or []:
                if isinstance(ix, dict):
                    yield ix
    except Exception:
        return


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(float(s))
        except Exception:
            return None
    return None


def _coerce_blockhash(v: Any) -> Optional[Hash]:
    """Coerce a blockhash value into a solders `Hash` across solana-py response variants."""
    if v is None:
        return None
    if isinstance(v, Hash):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        return Hash.from_string(s)
    # Some solana-py versions may return objects that stringify to the base58 blockhash.
    try:
        s = str(v).strip()
        if s:
            return Hash.from_string(s)
    except Exception:
        return None
    return None


def _coerce_signature(v: Any) -> Optional[Signature]:
    """Coerce a transaction signature into a solders `Signature` (for RPC calls)."""
    if v is None:
        return None
    if isinstance(v, Signature):
        return v
    try:
        s = str(v).strip()
        if not s:
            return None
        return Signature.from_string(s)
    except Exception:
        return None


def _signature_str(v: Any) -> str:
    """Return a stable string representation of a tx signature for logging/JSON."""
    return str(v).strip()


def _token_balances_by_owner_and_mint(
    meta: Dict[str, Any],
) -> Tuple[Dict[Tuple[str, str], int], Dict[Tuple[str, str], int]]:
    """
    Return (pre, post) mappings for summed SPL token balances keyed by (owner, mint),
    using raw base-unit `amount` strings from uiTokenAmount.
    """

    def collect(entries: Any) -> Dict[Tuple[str, str], int]:
        out: Dict[Tuple[str, str], int] = {}
        if not isinstance(entries, list):
            return out
        for e in entries:
            if not isinstance(e, dict):
                continue
            owner = e.get("owner")
            mint = e.get("mint")
            ui = e.get("uiTokenAmount") or {}
            amount_str = ui.get("amount")
            if not isinstance(owner, str) or not isinstance(
                mint, str
            ):
                continue
            amt = _safe_int(amount_str)
            if amt is None:
                continue
            key = (owner, mint)
            out[key] = out.get(key, 0) + amt
        return out

    pre = collect(meta.get("preTokenBalances"))
    post = collect(meta.get("postTokenBalances"))
    return pre, post


async def verify_solana_transaction(
    sig: Any,
    expected_amount_units: int,
    sender: str,
    payment_token: PaymentToken = PaymentToken.SOL,
    expected_recipient: Optional[str] = None,
    expected_mint: Optional[str] = None,
    commitment: str = "confirmed",
    max_wait_seconds: int = 30,
    poll_interval_seconds: float = 1.0,
) -> tuple[bool, str]:
    """Verify a Solana transaction signature (best-effort).

    This function is used after submitting a payment transaction to ensure the tx:
    - exists on-chain
    - is not failed (no error recorded)
    - has retrievable transaction details

    Args:
        sig: Transaction signature (base58 string).
        expected_amount_units: Expected amount in smallest units (lamports for SOL, token base units for SPL).
            NOTE: currently not enforced (see security note at top of file).
        sender: Expected sender public key string.
            NOTE: currently not enforced (see security note at top of file).
        payment_token: Which token type this payment represents (SOL/USDC).

    Returns:
        (ok, message) where ok is True when the transaction looks successful.

    Production behavior:
    - Fetches the transaction in `jsonParsed` form and validates:
      - tx exists and is successful
      - **sender**, **recipient**, and **amount** match expectations for SOL transfers
      - for SPL tokens, validates owner-level token balance deltas by (owner, mint)

    Args (additional):
        expected_recipient: Required for production-grade verification. For SOL this is the destination pubkey.
            For SPL tokens, pass the expected **owner** (e.g., treasury pubkey) whose token holdings should increase.
        expected_mint: For SPL tokens, the expected mint address (e.g., USDC mint).
        commitment: Desired confirmation level (processed|confirmed|finalized). Used for polling.
        max_wait_seconds: Max time to wait for `get_transaction` to become available.
        poll_interval_seconds: Poll interval while waiting for tx details.
    """
    try:
        # Keep both forms:
        # - sig_str: JSON/log safe
        # - sig_rpc: solders Signature for solana-py builds that require it
        sig_str = _signature_str(sig)
        sig_rpc: Any = _coerce_signature(sig_str) or sig_str
        _dbg(
            "verify_solana_transaction start: sig_str={} sig_type={} sig_rpc_type={} commitment={} token={}",
            sig_str,
            _type_name(sig),
            _type_name(sig_rpc),
            commitment,
            getattr(payment_token, "value", payment_token),
        )

        def _normalize_confirmation_status(
            status: Any,
        ) -> Optional[str]:
            """
            Normalize various confirmation status shapes into one of:
            processed | confirmed | finalized

            solana-py / solders may return:
            - "confirmed" (str)
            - TransactionConfirmationStatus.Finalized (enum-like)
            - TransactionConfirmationStatus.Finalized wrapped in other objects
            """
            if status is None:
                return None
            if isinstance(status, str):
                s = status.strip().lower()
                return s or None

            # Enum-like: prefer `.name`
            name = getattr(status, "name", None)
            if isinstance(name, str) and name:
                return name.strip().lower()

            # Sometimes `.value` is present
            value = getattr(status, "value", None)
            if isinstance(value, str) and value:
                return value.strip().lower()

            # Fallback: stringification often looks like "TransactionConfirmationStatus.Finalized"
            try:
                s = str(status).strip()
                if not s:
                    return None
                if "." in s:
                    s = s.split(".")[-1]
                return s.strip().lower()
            except Exception:
                return None

        def _commitment_ok(status: Any) -> bool:
            normalized = _normalize_confirmation_status(status)
            if not normalized:
                return False
            want = (
                _normalize_confirmation_status(commitment)
                or "confirmed"
            )
            rank = {"processed": 1, "confirmed": 2, "finalized": 3}
            return rank.get(normalized, 0) >= rank.get(want, 2)

        async with SolanaClient(config.SOLANA_RPC_URL) as client:
            # Wait for signature status + tx details to become available.
            # Even after `confirm_transaction`, some RPC nodes take a moment before `get_transaction` returns data.
            tx: Optional[Dict[str, Any]] = None
            last_status: Optional[str] = None
            import time

            deadline = time.time() + max_wait_seconds
            while time.time() < deadline:
                try:
                    st = await client.get_signature_statuses(
                        [sig_rpc]
                    )
                except TypeError:
                    st = await client.get_signature_statuses(
                        [sig_str]
                    )
                _dbg(
                    "get_signature_statuses: sig_rpc_type={} resp_type={} resp={}",
                    _type_name(sig_rpc),
                    _type_name(st),
                    _as_dict(st),
                )
                if st.value and st.value[0] is not None:
                    if st.value[0].err:
                        return False, "Transaction failed on-chain."
                    last_status = getattr(
                        st.value[0], "confirmation_status", None
                    ) or getattr(
                        st.value[0], "confirmationStatus", None
                    )
                    # Some versions expose dict-like status objects
                    if isinstance(st.value[0], dict):
                        last_status = st.value[0].get(
                            "confirmationStatus"
                        ) or st.value[0].get("confirmation_status")
                    _dbg(
                        "signature status row: row_type={} confirmation_status={} normalized_ok={}",
                        _type_name(st.value[0]),
                        last_status,
                        _commitment_ok(last_status or "confirmed"),
                    )

                # Try to fetch tx details; prefer jsonParsed, but fall back if unsupported.
                try:
                    tx_details = await client.get_transaction(
                        sig_rpc,
                        encoding="jsonParsed",
                        max_supported_transaction_version=0,
                    )
                except TypeError:
                    # Some solana-py versions expect a string signature and/or don't support encoding kwarg.
                    try:
                        tx_details = await client.get_transaction(
                            sig_str,
                            encoding="jsonParsed",
                            max_supported_transaction_version=0,
                        )
                    except TypeError:
                        tx_details = await client.get_transaction(
                            sig_str,
                            max_supported_transaction_version=0,
                        )
                _dbg(
                    "get_transaction: sig_str={} resp_type={} resp_keys={}",
                    sig_str,
                    _type_name(tx_details),
                    (
                        list(
                            _unwrap_get_transaction_response(
                                tx_details
                            ).keys()
                        )
                        if _unwrap_get_transaction_response(
                            tx_details
                        )
                        else None
                    ),
                )

                tx = _unwrap_get_transaction_response(tx_details)
                if tx and _commitment_ok(last_status or "confirmed"):
                    break

                await asyncio.sleep(poll_interval_seconds)

            if not tx:
                return False, "Could not fetch transaction details."

            meta = tx.get("meta") or {}
            if meta.get("err") is not None:
                return False, "Transaction failed on-chain."

            if payment_token == PaymentToken.SOL:
                if not expected_recipient:
                    return (
                        False,
                        "Missing expected_recipient for SOL verification.",
                    )

                # Prefer instruction parsing (most precise)
                matched = False
                for ix in _iter_instructions_json_parsed(tx):
                    if (
                        ix.get("program") or ix.get("programId")
                    ) not in {"system"}:
                        continue
                    parsed = ix.get("parsed")
                    if not isinstance(parsed, dict):
                        continue
                    if parsed.get("type") != "transfer":
                        continue
                    info = parsed.get("info") or {}
                    source = info.get("source")
                    dest = info.get("destination")
                    lamports = _safe_int(info.get("lamports"))
                    if (
                        source == sender
                        and dest == expected_recipient
                        and lamports == expected_amount_units
                    ):
                        matched = True
                        break

                if matched:
                    logger.info(
                        f"SOL payment verified: sig={sig_str} sender={sender} recipient={expected_recipient} lamports={expected_amount_units}"
                    )
                    return True, "Verified"

                # Fallback: balance delta check (less precise but still strong for simple transfers)
                msg = (tx.get("transaction") or {}).get(
                    "message"
                ) or {}
                keys: List[Any] = msg.get("accountKeys") or []
                # accountKeys may be list[str] or list[dict{pubkey:...}]
                key_strs: List[str] = []
                for k in keys:
                    if isinstance(k, str):
                        key_strs.append(k)
                    elif isinstance(k, dict) and isinstance(
                        k.get("pubkey"), str
                    ):
                        key_strs.append(k["pubkey"])
                try:
                    sender_idx = key_strs.index(sender)
                    recipient_idx = key_strs.index(expected_recipient)
                except ValueError:
                    return (
                        False,
                        "Sender/recipient not found in transaction account keys.",
                    )

                pre = meta.get("preBalances") or []
                post = meta.get("postBalances") or []
                if not (
                    isinstance(pre, list) and isinstance(post, list)
                ):
                    return (
                        False,
                        "Missing balance arrays for verification.",
                    )
                if (
                    sender_idx >= len(pre)
                    or sender_idx >= len(post)
                    or recipient_idx >= len(pre)
                    or recipient_idx >= len(post)
                ):
                    return False, "Balance indices out of range."

                sender_delta = _safe_int(post[sender_idx]) - _safe_int(pre[sender_idx])  # type: ignore[operator]
                recipient_delta = _safe_int(post[recipient_idx]) - _safe_int(pre[recipient_idx])  # type: ignore[operator]
                if sender_delta is None or recipient_delta is None:
                    return False, "Unable to compute balance deltas."

                if (
                    recipient_delta == expected_amount_units
                    and sender_delta <= -expected_amount_units
                ):
                    logger.info(
                        f"SOL payment verified (delta): sig={sig_str} sender={sender} recipient={expected_recipient} lamports={expected_amount_units}"
                    )
                    return True, "Verified"

                return (
                    False,
                    "Payment mismatch: could not find exact SOL transfer to expected recipient/amount.",
                )

            # SPL token verification (e.g., USDC)
            if not expected_recipient:
                return (
                    False,
                    "Missing expected_recipient (owner) for SPL verification.",
                )
            mint = expected_mint or (
                config.USDC_MINT_ADDRESS
                if payment_token == PaymentToken.USDC
                else None
            )
            if not mint:
                return (
                    False,
                    "Missing expected_mint for SPL verification.",
                )

            pre_map, post_map = _token_balances_by_owner_and_mint(
                meta
            )
            rec_key = (expected_recipient, mint)
            snd_key = (sender, mint)
            recipient_delta = post_map.get(rec_key, 0) - pre_map.get(
                rec_key, 0
            )
            sender_delta = post_map.get(snd_key, 0) - pre_map.get(
                snd_key, 0
            )

            if (
                recipient_delta == expected_amount_units
                and sender_delta <= -expected_amount_units
            ):
                logger.info(
                    f"SPL payment verified: sig={sig_str} sender={sender} owner={expected_recipient} mint={mint} amount={expected_amount_units}"
                )
                return True, "Verified"

            return (
                False,
                "Payment mismatch: SPL token balance deltas do not match expected amount.",
            )

    except Exception as e:
        # Log full traceback server-side for debugging/ops.
        # Avoid logging any secrets; signature + pubkeys are safe.
        logger.opt(exception=True).error(
            "verify_solana_transaction failed: sig={} token={} sender={} expected_recipient={} expected_amount_units={} commitment={}",
            sig_str if "sig_str" in locals() else _signature_str(sig),
            getattr(payment_token, "value", payment_token),
            sender,
            expected_recipient,
            expected_amount_units,
            commitment,
        )
        return False, f"Verification error: {str(e)}"


def parse_keypair_from_string(private_key_str: str) -> Keypair:
    """Parse a Solana payer keypair from a string (without logging secrets).

    Supported formats:
    - JSON array of ints (common Solana exported secret key array)
    - Base58 keypair string (when supported by the installed solders build)

    Args:
        private_key_str: Secret key encoding.

    Returns:
        solders `Keypair`

    Raises:
        ValueError: If the key is empty or the format is unsupported/invalid.
    """
    try:
        s = (private_key_str or "").strip()
        if not s:
            raise ValueError("Empty private_key")

        if s.startswith("["):
            arr = json.loads(s)
            if not isinstance(arr, list) or not all(
                isinstance(x, int) for x in arr
            ):
                raise ValueError(
                    "Invalid JSON private key; expected a list of ints"
                )
            key_bytes = bytes(arr)
            return Keypair.from_bytes(key_bytes)

        if hasattr(Keypair, "from_base58_string"):
            return Keypair.from_base58_string(s)  # type: ignore[attr-defined]

        raise ValueError(
            "Unsupported private_key format for this runtime. Provide a JSON array of ints."
        )
    except Exception:
        # Never log the key itself. Just log that parsing failed.
        logger.opt(exception=True).error(
            "parse_keypair_from_string failed"
        )
        raise


async def send_and_confirm_sol_payment(
    *,
    payer: Keypair,
    recipient_pubkey_str: str,
    lamports: int,
    skip_preflight: bool,
    commitment: str,
) -> str:
    """Build, sign, send, and confirm a native SOL transfer.

    Args:
        payer: solders `Keypair` that pays the lamports and signs the tx.
        recipient_pubkey_str: Recipient pubkey (base58 string).
        lamports: Amount of SOL to send in lamports (must be > 0).
        skip_preflight: If True, skip preflight simulation.
        commitment: Confirmation commitment to wait for (processed|confirmed|finalized).

    Returns:
        Transaction signature (base58 string).

    Raises:
        ValueError: If lamports <= 0.
        RuntimeError: If blockhash cannot be fetched, tx cannot be sent, or tx fails.
    """
    if lamports <= 0:
        raise ValueError("lamports must be > 0")

    try:
        recipient = Pubkey.from_string(recipient_pubkey_str)
        _dbg(
            "send_and_confirm_sol_payment start: payer_pubkey={} recipient={} lamports={} skip_preflight={} commitment={}",
            str(payer.pubkey()),
            recipient_pubkey_str,
            lamports,
            skip_preflight,
            commitment,
        )
        ix = transfer(
            TransferParams(
                from_pubkey=payer.pubkey(),
                to_pubkey=recipient,
                lamports=lamports,
            )
        )

        async with SolanaClient(config.SOLANA_RPC_URL) as client:
            latest = await client.get_latest_blockhash()
            blockhash_val: Any = None
            if isinstance(latest, dict):
                blockhash_val = (
                    (latest.get("result") or {}).get("value") or {}
                ).get("blockhash")
            else:
                value = getattr(latest, "value", None)
                blockhash_val = (
                    getattr(value, "blockhash", None)
                    if value
                    else None
                )
            _dbg(
                "get_latest_blockhash: resp_type={} blockhash_val_type={} blockhash_val={}",
                _type_name(latest),
                _type_name(blockhash_val),
                blockhash_val,
            )

            recent_blockhash = _coerce_blockhash(blockhash_val)
            if not recent_blockhash:
                raise RuntimeError(
                    f"Could not fetch latest blockhash: {latest}"
                )
            _dbg(
                "recent_blockhash coerced: type={} value={}",
                _type_name(recent_blockhash),
                recent_blockhash,
            )

            if hasattr(SoldersTransaction, "new_signed_with_payer"):
                tx = SoldersTransaction.new_signed_with_payer(  # type: ignore[attr-defined]
                    [ix],
                    payer.pubkey(),
                    [payer],
                    recent_blockhash,
                )
            else:
                from solders.message import Message

                msg = Message.new_with_blockhash(
                    [ix], payer.pubkey(), recent_blockhash
                )
                tx = SoldersTransaction.new_unsigned(msg)
                tx.sign([payer], recent_blockhash)

            raw_tx = (
                tx.to_bytes()
                if hasattr(tx, "to_bytes")
                else bytes(tx)
            )

            resp = await client.send_raw_transaction(
                raw_tx,
                opts=TxOpts(
                    skip_preflight=skip_preflight,
                    preflight_commitment=commitment,
                ),
            )
            _dbg(
                "send_raw_transaction: resp_type={} resp={}",
                _type_name(resp),
                _as_dict(resp),
            )

            sig = (
                resp.get("result")
                if isinstance(resp, dict)
                else getattr(resp, "value", None)
                or getattr(resp, "result", None)
            )
            if not sig:
                raise RuntimeError(
                    f"Failed to send transaction: {resp}"
                )
            sig_str = _signature_str(sig)
            if not sig_str:
                raise RuntimeError(
                    f"Failed to parse transaction signature: {sig}"
                )
            sig_rpc: Any = _coerce_signature(sig_str) or sig_str
            _dbg(
                "signature parsed: sig_str={} sig_type={} sig_rpc_type={}",
                sig_str,
                _type_name(sig),
                _type_name(sig_rpc),
            )

            if hasattr(client, "confirm_transaction"):
                # solana-py version differences:
                # - some builds want a string signature
                # - others want a solders `Signature`
                try:
                    await client.confirm_transaction(sig_rpc, commitment=commitment)  # type: ignore[arg-type]
                except TypeError:
                    await client.confirm_transaction(sig_str, commitment=commitment)  # type: ignore[arg-type]
            else:
                for _ in range(30):
                    try:
                        st = await client.get_signature_statuses(
                            [sig_rpc]
                        )
                    except TypeError:
                        st = await client.get_signature_statuses(
                            [sig_str]
                        )
                    if st.value and st.value[0] is not None:
                        if st.value[0].err:
                            raise RuntimeError(
                                "Transaction failed on-chain"
                            )
                        return sig_str
                    await asyncio.sleep(1)

            return sig_str
    except Exception:
        # Log full traceback with non-sensitive context. Do NOT log payer secret key.
        logger.opt(exception=True).error(
            "send_and_confirm_sol_payment failed: payer={} recipient={} lamports={} skip_preflight={} commitment={}",
            str(payer.pubkey()),
            recipient_pubkey_str,
            lamports,
            skip_preflight,
            commitment,
        )
        raise


async def send_and_confirm_split_sol_payment(
    *,
    payer: Keypair,
    treasury_pubkey_str: str,
    recipient_pubkey_str: str,
    treasury_lamports: int,
    recipient_lamports: int,
    skip_preflight: bool,
    commitment: str,
) -> str:
    """Build, sign, send, and confirm a split SOL transfer (treasury fee + recipient payment).

    Sends two transfers in a single atomic transaction:
    1. Treasury receives the processing fee
    2. Recipient receives the remainder

    Args:
        payer: solders `Keypair` that pays the lamports and signs the tx.
        treasury_pubkey_str: Treasury pubkey (base58 string) for processing fee.
        recipient_pubkey_str: Recipient pubkey (base58 string) for main payment.
        treasury_lamports: Amount of SOL to send to treasury (must be >= 0).
        recipient_lamports: Amount of SOL to send to recipient (must be > 0).
        skip_preflight: If True, skip preflight simulation.
        commitment: Confirmation commitment to wait for (processed|confirmed|finalized).

    Returns:
        Transaction signature (base58 string).

    Raises:
        ValueError: If recipient_lamports <= 0 or treasury_lamports < 0.
        RuntimeError: If blockhash cannot be fetched, tx cannot be sent, or tx fails.
    """
    if recipient_lamports <= 0:
        raise ValueError("recipient_lamports must be > 0")
    if treasury_lamports < 0:
        raise ValueError("treasury_lamports must be >= 0")

    try:
        treasury = Pubkey.from_string(treasury_pubkey_str)
        recipient = Pubkey.from_string(recipient_pubkey_str)
        _dbg(
            "send_and_confirm_split_sol_payment start: payer_pubkey={} treasury={} recipient={} treasury_lamports={} recipient_lamports={} skip_preflight={} commitment={}",
            str(payer.pubkey()),
            treasury_pubkey_str,
            recipient_pubkey_str,
            treasury_lamports,
            recipient_lamports,
            skip_preflight,
            commitment,
        )

        # Create transfer instructions
        instructions = []
        if treasury_lamports > 0:
            instructions.append(
                transfer(
                    TransferParams(
                        from_pubkey=payer.pubkey(),
                        to_pubkey=treasury,
                        lamports=treasury_lamports,
                    )
                )
            )
        instructions.append(
            transfer(
                TransferParams(
                    from_pubkey=payer.pubkey(),
                    to_pubkey=recipient,
                    lamports=recipient_lamports,
                )
            )
        )

        async with SolanaClient(config.SOLANA_RPC_URL) as client:
            latest = await client.get_latest_blockhash()
            blockhash_val: Any = None
            if isinstance(latest, dict):
                blockhash_val = (
                    (latest.get("result") or {}).get("value") or {}
                ).get("blockhash")
            else:
                value = getattr(latest, "value", None)
                blockhash_val = (
                    getattr(value, "blockhash", None)
                    if value
                    else None
                )
            _dbg(
                "get_latest_blockhash: resp_type={} blockhash_val_type={} blockhash_val={}",
                _type_name(latest),
                _type_name(blockhash_val),
                blockhash_val,
            )

            recent_blockhash = _coerce_blockhash(blockhash_val)
            if not recent_blockhash:
                raise RuntimeError(
                    f"Could not fetch latest blockhash: {latest}"
                )
            _dbg(
                "recent_blockhash coerced: type={} value={}",
                _type_name(recent_blockhash),
                recent_blockhash,
            )

            if hasattr(SoldersTransaction, "new_signed_with_payer"):
                tx = SoldersTransaction.new_signed_with_payer(  # type: ignore[attr-defined]
                    instructions,
                    payer.pubkey(),
                    [payer],
                    recent_blockhash,
                )
            else:
                from solders.message import Message

                msg = Message.new_with_blockhash(
                    instructions, payer.pubkey(), recent_blockhash
                )
                tx = SoldersTransaction.new_unsigned(msg)
                tx.sign([payer], recent_blockhash)

            raw_tx = (
                tx.to_bytes()
                if hasattr(tx, "to_bytes")
                else bytes(tx)
            )

            resp = await client.send_raw_transaction(
                raw_tx,
                opts=TxOpts(
                    skip_preflight=skip_preflight,
                    preflight_commitment=commitment,
                ),
            )
            _dbg(
                "send_raw_transaction: resp_type={} resp={}",
                _type_name(resp),
                _as_dict(resp),
            )

            sig = (
                resp.get("result")
                if isinstance(resp, dict)
                else getattr(resp, "value", None)
                or getattr(resp, "result", None)
            )
            if not sig:
                raise RuntimeError(
                    f"Failed to send transaction: {resp}"
                )
            sig_str = _signature_str(sig)
            if not sig_str:
                raise RuntimeError(
                    f"Failed to parse transaction signature: {sig}"
                )
            sig_rpc: Any = _coerce_signature(sig_str) or sig_str
            _dbg(
                "signature parsed: sig_str={} sig_type={} sig_rpc_type={}",
                sig_str,
                _type_name(sig),
                _type_name(sig_rpc),
            )

            if hasattr(client, "confirm_transaction"):
                # solana-py version differences:
                # - some builds want a string signature
                # - others want a solders `Signature`
                try:
                    await client.confirm_transaction(sig_rpc, commitment=commitment)  # type: ignore[arg-type]
                except TypeError:
                    await client.confirm_transaction(sig_str, commitment=commitment)  # type: ignore[arg-type]
            else:
                for _ in range(30):
                    try:
                        st = await client.get_signature_statuses(
                            [sig_rpc]
                        )
                    except TypeError:
                        st = await client.get_signature_statuses(
                            [sig_str]
                        )
                    if st.value and st.value[0] is not None:
                        if st.value[0].err:
                            raise RuntimeError(
                                "Transaction failed on-chain"
                            )
                        return sig_str
                    await asyncio.sleep(1)

            return sig_str
    except Exception:
        # Log full traceback with non-sensitive context. Do NOT log payer secret key.
        logger.opt(exception=True).error(
            "send_and_confirm_split_sol_payment failed: payer={} treasury={} recipient={} treasury_lamports={} recipient_lamports={} skip_preflight={} commitment={}",
            str(payer.pubkey()),
            treasury_pubkey_str,
            recipient_pubkey_str,
            treasury_lamports,
            recipient_lamports,
            skip_preflight,
            commitment,
        )
        raise
