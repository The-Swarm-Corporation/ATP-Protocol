/*
 * ATP Settlement Service - Ultra High-Performance Rust Implementation
 *
 * This service provides a centralized, immutable settlement API that handles:
 * - Usage token parsing from various API formats
 * - Payment amount calculation
 * - Solana payment execution
 * - Settlement verification
 *
 * Built with Axum for maximum performance and async efficiency.
 */

use axum::{
    extract::State,
    http::StatusCode,
    response::{Html, Json},
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use solana_client::rpc_client::RpcClient;
use solana_sdk::{
    instruction::{AccountMeta, Instruction},
    message::Message,
    pubkey::Pubkey,
    signature::{Keypair, Signer},
    transaction::Transaction,
};
use std::{
    collections::HashMap,
    convert::TryInto,
    str::FromStr,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::sync::RwLock;
use tower::ServiceBuilder;
use tower_http::cors::CorsLayer;
use tracing::{info, warn};
use tracing_subscriber;
use utoipa::OpenApi;
use utoipa_swagger_ui::SwaggerUi;

// Configuration
#[derive(Clone)]
struct Config {
    solana_rpc_url: String,
    swarms_treasury_pubkey: String,
    settlement_fee_percent: f64,
    #[allow(dead_code)]
    usdc_mint_address: String,
    #[allow(dead_code)]
    usdc_decimals: u8,
}

impl Config {
    fn from_env() -> Self {
        Self {
            solana_rpc_url: std::env::var("SOLANA_RPC_URL")
                .unwrap_or_else(|_| "https://api.mainnet-beta.solana.com".to_string()),
            swarms_treasury_pubkey: std::env::var("SWARMS_TREASURY_PUBKEY")
                .unwrap_or_else(|_| "7MaX4muAn8ZQREJxnupm8sgokwFHujgrGfH9Qn81BuEV".to_string()),
            settlement_fee_percent: std::env::var("SETTLEMENT_FEE_PERCENT")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(0.05),
            usdc_mint_address: std::env::var("USDC_MINT_ADDRESS")
                .unwrap_or_else(|_| "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v".to_string()),
            usdc_decimals: std::env::var("USDC_DECIMALS")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(6),
        }
    }
}

// Payment Token Enum
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default, utoipa::ToSchema)]
#[serde(rename_all = "UPPERCASE")]
enum PaymentToken {
    #[default]
    SOL,
    USDC,
}

// Request/Response Models
#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[schema(example = json!({
    "usage_data": {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150
    }
}))]
struct ParseUsageRequest {
    #[schema(example = json!({
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150
    }))]
    usage_data: Value,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct ParseUsageResponse {
    #[schema(example = 100)]
    input_tokens: Option<i64>,
    #[schema(example = 50)]
    output_tokens: Option<i64>,
    #[schema(example = 150)]
    total_tokens: Option<i64>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[schema(example = json!({
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500
    },
    "input_cost_per_million_usd": 2.50,
    "output_cost_per_million_usd": 10.00,
    "payment_token": "SOL"
}))]
struct CalculatePaymentRequest {
    #[schema(example = json!({
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500
    }))]
    usage: Value,
    #[schema(example = 2.50)]
    input_cost_per_million_usd: f64,
    #[schema(example = 10.00)]
    output_cost_per_million_usd: f64,
    #[serde(default)]
    #[schema(example = "SOL")]
    payment_token: PaymentToken,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct PricingInfo {
    #[schema(example = 0.0075)]
    usd_cost: f64,
    #[schema(example = "settlement_service_rates")]
    source: String,
    input_tokens: Option<i64>,
    output_tokens: Option<i64>,
    total_tokens: Option<i64>,
    input_cost_per_million_usd: f64,
    output_cost_per_million_usd: f64,
    input_cost_usd: f64,
    output_cost_usd: f64,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct PaymentAmounts {
    total_amount_units: u64,
    total_amount_token: f64,
    fee_amount_units: u64,
    fee_amount_token: f64,
    agent_amount_units: u64,
    agent_amount_token: f64,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct CalculatePaymentResponse {
    #[schema(example = "calculated")]
    status: String,
    reason: Option<String>,
    pricing: PricingInfo,
    payment_amounts: Option<PaymentAmounts>,
    token_price_usd: Option<f64>,
}

#[derive(Debug, Deserialize, utoipa::ToSchema)]
#[schema(example = json!({
    "private_key": "[1,2,3,...64 bytes...]",
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500
    },
    "input_cost_per_million_usd": 2.50,
    "output_cost_per_million_usd": 10.00,
    "recipient_pubkey": "RecipientWalletAddressHere",
    "payment_token": "SOL",
    "treasury_pubkey": null,
    "skip_preflight": false,
    "commitment": "confirmed"
}))]
struct SettlePaymentRequest {
    #[schema(example = "[1,2,3,...64 bytes...]")]
    private_key: String,
    usage: Value,
    input_cost_per_million_usd: f64,
    output_cost_per_million_usd: f64,
    #[schema(example = "RecipientWalletAddressHere")]
    recipient_pubkey: String,
    #[serde(default)]
    payment_token: PaymentToken,
    treasury_pubkey: Option<String>,
    #[serde(default)]
    skip_preflight: bool,
    #[serde(default = "default_commitment")]
    commitment: String,
}

fn default_commitment() -> String {
    "confirmed".to_string()
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct TreasuryPayment {
    pubkey: String,
    amount_lamports: u64,
    amount_sol: f64,
    amount_usd: f64,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct RecipientPayment {
    pubkey: String,
    amount_lamports: u64,
    amount_sol: f64,
    amount_usd: f64,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct PaymentDetails {
    total_amount_lamports: u64,
    total_amount_sol: f64,
    total_amount_usd: f64,
    treasury: TreasuryPayment,
    recipient: RecipientPayment,
}

#[derive(Debug, Serialize, utoipa::ToSchema)]
struct SettlePaymentResponse {
    #[schema(example = "paid")]
    status: String,
    #[schema(example = "5j7s8K9L0mN1oP2qR3sT4uV5wX6yZ7aB8cD9eF0gH1iJ2kL3mN4oP5qR")]
    transaction_signature: Option<String>,
    pricing: PricingInfo,
    payment: Option<PaymentDetails>,
}

// Token Price Fetcher with caching
struct TokenPriceFetcher {
    cache: Arc<RwLock<HashMap<String, (f64, u64)>>>,
    cache_ttl: u64,
}

impl TokenPriceFetcher {
    fn new() -> Self {
        Self {
            cache: Arc::new(RwLock::new(HashMap::new())),
            cache_ttl: 60, // 60 seconds
        }
    }

    async fn get_price_usd(&self, token: &str) -> Result<f64, Box<dyn std::error::Error>> {
        // USDC is pegged to USD
        if token.to_uppercase() == "USDC" {
            return Ok(1.0);
        }

        let token_upper = token.to_uppercase();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();

        // Check cache
        {
            let cache = self.cache.read().await;
            if let Some((price, timestamp)) = cache.get(&token_upper) {
                if now - timestamp < self.cache_ttl {
                    return Ok(*price);
                }
            }
        }

        // Fetch from CoinGecko
        let coingecko_ids: HashMap<&str, &str> = [("SOL", "solana")].into_iter().collect();
        let coingecko_id = coingecko_ids
            .get(token_upper.as_str())
            .ok_or_else(|| format!("Unknown token: {}", token))?;

        let url = format!(
            "https://api.coingecko.com/api/v3/simple/price?ids={}&vs_currencies=usd",
            coingecko_id
        );

        let client = reqwest::Client::new();
        let response = client
            .get(&url)
            .timeout(Duration::from_secs(10))
            .send()
            .await?;

        if !response.status().is_success() {
            // Try to use cached value if available
            let cache = self.cache.read().await;
            if let Some((price, _)) = cache.get(&token_upper) {
                warn!("Failed to fetch {} price, using cached value", token);
                return Ok(*price);
            }
            return Err(format!("Failed to fetch price: {}", response.status()).into());
        }

        let data: Value = response.json().await?;
        let price = data[coingecko_id]["usd"]
            .as_f64()
            .ok_or_else(|| format!("Price not found for {}", token))?;

        // Update cache
        {
            let mut cache = self.cache.write().await;
            cache.insert(token_upper.clone(), (price, now));
        }

        Ok(price)
    }
}

// Application State
#[derive(Clone)]
struct AppState {
    config: Config,
    price_fetcher: Arc<TokenPriceFetcher>,
}

// Core Business Logic

fn safe_int(value: &Value) -> Option<i64> {
    match value {
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().map(|f| f as i64)),
        Value::String(s) => s.trim().parse().ok(),
        _ => None,
    }
}

fn parse_usage_tokens(usage_data: &Value) -> (Option<i64>, Option<i64>, Option<i64>) {
    let obj = match usage_data.as_object() {
        Some(o) => o,
        None => return (None, None, None),
    };

    // Try OpenAI format: prompt_tokens, completion_tokens, total_tokens
    if let (Some(prompt), Some(completion)) = (
        obj.get("prompt_tokens").and_then(safe_int),
        obj.get("completion_tokens").and_then(safe_int),
    ) {
        let total = obj
            .get("total_tokens")
            .and_then(safe_int)
            .or_else(|| Some(prompt + completion));
        return (Some(prompt), Some(completion), total);
    }

    // Try Anthropic/Generic format: input_tokens, output_tokens, total_tokens
    if let (Some(input), Some(output)) = (
        obj.get("input_tokens").and_then(safe_int),
        obj.get("output_tokens").and_then(safe_int),
    ) {
        let total = obj
            .get("total_tokens")
            .and_then(safe_int)
            .or_else(|| Some(input + output));
        return (Some(input), Some(output), total);
    }

    // Try Google/Gemini format
    if let (Some(prompt), Some(candidates)) = (
        obj.get("promptTokenCount").and_then(safe_int),
        obj.get("candidatesTokenCount").and_then(safe_int),
    ) {
        let total = obj
            .get("totalTokenCount")
            .and_then(safe_int)
            .or_else(|| Some(prompt + candidates));
        return (Some(prompt), Some(candidates), total);
    }

    // Try Cohere format
    if let Some(tokens) = obj.get("tokens").and_then(safe_int) {
        return (
            obj.get("input_tokens").and_then(safe_int),
            obj.get("output_tokens").and_then(safe_int),
            Some(tokens),
        );
    }

    // Try nested usage object
    if let Some(usage) = obj.get("usage").and_then(|v| v.as_object()) {
        return parse_usage_tokens(&Value::Object(usage.clone()));
    }

    // Try meta.usage format
    if let Some(meta) = obj.get("meta").and_then(|v| v.as_object()) {
        if let Some(usage) = meta.get("usage") {
            return parse_usage_tokens(usage);
        }
    }

    // Try statistics format
    if let Some(stats) = obj.get("statistics").and_then(|v| v.as_object()) {
        let input = stats
            .get("input_tokens")
            .or_else(|| stats.get("prompt_tokens"))
            .or_else(|| stats.get("tokens_in"))
            .and_then(safe_int);
        let output = stats
            .get("output_tokens")
            .or_else(|| stats.get("completion_tokens"))
            .or_else(|| stats.get("tokens_out"))
            .and_then(safe_int);
        let total = stats
            .get("total_tokens")
            .or_else(|| stats.get("tokens"))
            .and_then(safe_int);
        return (input, output, total);
    }

    (None, None, None)
}

fn calculate_payment_amounts(
    usd_cost: f64,
    token_price_usd: f64,
    _payment_token: PaymentToken,
    fee_percent: f64,
    decimals: u8,
) -> PaymentAmounts {
    let total_amount_token = usd_cost / token_price_usd;
    let fee_amount_token = total_amount_token * fee_percent;
    let agent_amount_token = total_amount_token - fee_amount_token;

    let multiplier = 10_u64.pow(decimals as u32);
    let total_amount_units = (total_amount_token * multiplier as f64) as u64;
    let fee_amount_units = (fee_amount_token * multiplier as f64) as u64;
    let agent_amount_units = total_amount_units - fee_amount_units;

    PaymentAmounts {
        total_amount_units,
        total_amount_token,
        fee_amount_units,
        fee_amount_token,
        agent_amount_units,
        agent_amount_token,
    }
}

async fn calculate_payment_from_usage(
    usage: &Value,
    input_cost_per_million_usd: f64,
    output_cost_per_million_usd: f64,
    payment_token: PaymentToken,
    price_fetcher: &TokenPriceFetcher,
    fee_percent: f64,
) -> Result<CalculatePaymentResponse, Box<dyn std::error::Error>> {
    let (input_tokens, output_tokens, total_tokens) = parse_usage_tokens(usage);

    let input_cost = (input_tokens.unwrap_or(0) as f64 / 1_000_000.0) * input_cost_per_million_usd;
    let output_cost =
        (output_tokens.unwrap_or(0) as f64 / 1_000_000.0) * output_cost_per_million_usd;
    let usd_cost = input_cost + output_cost;

    let pricing = PricingInfo {
        usd_cost,
        source: "settlement_service_rates".to_string(),
        input_tokens,
        output_tokens,
        total_tokens,
        input_cost_per_million_usd,
        output_cost_per_million_usd,
        input_cost_usd: input_cost,
        output_cost_usd: output_cost,
    };

    if usd_cost <= 0.0 {
        return Ok(CalculatePaymentResponse {
            status: "skipped".to_string(),
            reason: Some("zero_cost".to_string()),
            pricing,
            payment_amounts: None,
            token_price_usd: None,
        });
    }

    let token_price_usd = price_fetcher
        .get_price_usd(match payment_token {
            PaymentToken::SOL => "SOL",
            PaymentToken::USDC => "USDC",
        })
        .await
        .unwrap_or(150.0);

    let decimals = match payment_token {
        PaymentToken::SOL => 9,
        PaymentToken::USDC => 6,
    };

    let payment_amounts = calculate_payment_amounts(
        usd_cost,
        token_price_usd,
        payment_token,
        fee_percent,
        decimals,
    );

    Ok(CalculatePaymentResponse {
        status: "calculated".to_string(),
        reason: None,
        pricing,
        payment_amounts: Some(payment_amounts),
        token_price_usd: Some(token_price_usd),
    })
}

fn parse_keypair_from_string(private_key_str: &str) -> Result<Keypair, Box<dyn std::error::Error>> {
    let s = private_key_str.trim();
    if s.is_empty() {
        return Err("Empty private_key".into());
    }

    // Try JSON array format
    if s.starts_with('[') {
        let arr: Vec<u8> = serde_json::from_str(s)?;
        // Keypair can be 32 bytes (secret key) or 64 bytes (full keypair)
        if arr.len() == 32 {
            let key_array: [u8; 32] = arr.try_into().map_err(|_| "Invalid keypair array length")?;
            return Ok(Keypair::new_from_array(key_array));
        } else if arr.len() == 64 {
            // Extract first 32 bytes (secret key) from full keypair
            let secret_key: [u8; 32] = arr[..32]
                .try_into()
                .map_err(|_| "Invalid keypair array length")?;
            return Ok(Keypair::new_from_array(secret_key));
        } else {
            return Err("Invalid keypair length, expected 32 or 64 bytes".into());
        }
    }

    // Try base58 format
    let bytes = bs58::decode(s).into_vec()?;
    if bytes.len() == 32 {
        let key_array: [u8; 32] = bytes
            .try_into()
            .map_err(|_| "Invalid keypair array length")?;
        Ok(Keypair::new_from_array(key_array))
    } else if bytes.len() == 64 {
        // Extract first 32 bytes (secret key) from full keypair
        let secret_key: [u8; 32] = bytes[..32]
            .try_into()
            .map_err(|_| "Invalid keypair array length")?;
        Ok(Keypair::new_from_array(secret_key))
    } else {
        Err("Invalid keypair length, expected 32 or 64 bytes".into())
    }
}

async fn send_and_confirm_split_sol_payment(
    payer: &Keypair,
    treasury_pubkey_str: &str,
    recipient_pubkey_str: &str,
    treasury_lamports: u64,
    recipient_lamports: u64,
    rpc_url: &str,
    _skip_preflight: bool,
    _commitment: &str,
) -> Result<String, Box<dyn std::error::Error>> {
    if recipient_lamports == 0 {
        return Err("recipient_lamports must be > 0".into());
    }

    let treasury_pubkey = Pubkey::from_str(treasury_pubkey_str)?;
    let recipient_pubkey = Pubkey::from_str(recipient_pubkey_str)?;

    // Clone data for blocking task
    // Extract secret key (first 32 bytes) from full keypair
    let payer_bytes_full = payer.to_bytes();
    let payer_secret: [u8; 32] = payer_bytes_full[..32]
        .try_into()
        .map_err(|_| "Failed to extract secret key")?;
    let rpc_url = rpc_url.to_string();
    let treasury_pubkey_clone = treasury_pubkey;
    let recipient_pubkey_clone = recipient_pubkey;

    // Run synchronous Solana operations in a blocking task
    let signature = tokio::task::spawn_blocking(move || -> Result<String, String> {
        let payer = Keypair::new_from_array(payer_secret);
        let client = RpcClient::new(rpc_url);

        let recent_blockhash = client
            .get_latest_blockhash()
            .map_err(|e| format!("Failed to get blockhash: {}", e))?;

        // Build transfer instructions manually
        // System program transfer instruction format:
        // - Instruction discriminator: 2 (u32 little-endian)
        // - Amount: u64 little-endian
        // System program ID: 11111111111111111111111111111111
        let system_program_id = Pubkey::from_str("11111111111111111111111111111111")
            .map_err(|e| format!("Failed to parse system program ID: {}", e))?;

        fn create_transfer_instruction(
            from: Pubkey,
            to: Pubkey,
            lamports: u64,
            system_program_id: Pubkey,
        ) -> Instruction {
            let mut data = Vec::with_capacity(12);
            data.extend_from_slice(&2u32.to_le_bytes()); // Transfer instruction discriminator
            data.extend_from_slice(&lamports.to_le_bytes());

            Instruction {
                program_id: system_program_id,
                accounts: vec![AccountMeta::new(from, true), AccountMeta::new(to, false)],
                data,
            }
        }

        let mut instructions = Vec::new();

        if treasury_lamports > 0 {
            instructions.push(create_transfer_instruction(
                payer.pubkey(),
                treasury_pubkey_clone,
                treasury_lamports,
                system_program_id,
            ));
        }

        instructions.push(create_transfer_instruction(
            payer.pubkey(),
            recipient_pubkey_clone,
            recipient_lamports,
            system_program_id,
        ));

        let message = Message::new(&instructions, Some(&payer.pubkey()));
        let mut transaction = Transaction::new_unsigned(message);
        transaction.sign(&[&payer], recent_blockhash);

        let signature = client
            .send_and_confirm_transaction(&transaction)
            .map_err(|e| format!("Failed to send transaction: {}", e))?;

        Ok(signature.to_string())
    })
    .await
    .map_err(|e| format!("Blocking task error: {}", e))??;

    Ok(signature)
}

async fn execute_settlement(
    private_key: &str,
    usage: &Value,
    input_cost_per_million_usd: f64,
    output_cost_per_million_usd: f64,
    recipient_pubkey: &str,
    payment_token: PaymentToken,
    treasury_pubkey: Option<&str>,
    skip_preflight: bool,
    commitment: &str,
    state: &AppState,
) -> Result<SettlePaymentResponse, Box<dyn std::error::Error>> {
    // Calculate payment
    let payment_calc = calculate_payment_from_usage(
        usage,
        input_cost_per_million_usd,
        output_cost_per_million_usd,
        payment_token,
        &state.price_fetcher,
        state.config.settlement_fee_percent,
    )
    .await?;

    if payment_calc.status == "skipped" {
        return Ok(SettlePaymentResponse {
            status: "skipped".to_string(),
            transaction_signature: None,
            pricing: payment_calc.pricing,
            payment: None,
        });
    }

    if payment_token != PaymentToken::SOL {
        return Err("Automatic settlement currently supports SOL only".into());
    }

    let payment_amounts = payment_calc
        .payment_amounts
        .ok_or("Missing payment amounts")?;
    let usd_cost = payment_calc.pricing.usd_cost;

    // Parse keypair
    let payer = parse_keypair_from_string(private_key)?;

    // Use treasury from config if not provided
    let treasury_pubkey_str = treasury_pubkey.unwrap_or(&state.config.swarms_treasury_pubkey);

    // Execute split payment
    let tx_sig = send_and_confirm_split_sol_payment(
        &payer,
        treasury_pubkey_str,
        recipient_pubkey,
        payment_amounts.fee_amount_units,
        payment_amounts.agent_amount_units,
        &state.config.solana_rpc_url,
        skip_preflight,
        commitment,
    )
    .await?;

    Ok(SettlePaymentResponse {
        status: "paid".to_string(),
        transaction_signature: Some(tx_sig),
        pricing: payment_calc.pricing,
        payment: Some(PaymentDetails {
            total_amount_lamports: payment_amounts.total_amount_units,
            total_amount_sol: payment_amounts.total_amount_token,
            total_amount_usd: usd_cost,
            treasury: TreasuryPayment {
                pubkey: treasury_pubkey_str.to_string(),
                amount_lamports: payment_amounts.fee_amount_units,
                amount_sol: payment_amounts.fee_amount_token,
                amount_usd: usd_cost * state.config.settlement_fee_percent,
            },
            recipient: RecipientPayment {
                pubkey: recipient_pubkey.to_string(),
                amount_lamports: payment_amounts.agent_amount_units,
                amount_sol: payment_amounts.agent_amount_token,
                amount_usd: usd_cost * (1.0 - state.config.settlement_fee_percent),
            },
        }),
    })
}

// OpenAPI Schema
#[derive(OpenApi)]
#[openapi(
    paths(
        health_check,
        parse_usage_endpoint,
        calculate_payment_endpoint,
        settle_endpoint,
    ),
    components(schemas(
        ParseUsageRequest,
        ParseUsageResponse,
        CalculatePaymentRequest,
        CalculatePaymentResponse,
        PricingInfo,
        PaymentAmounts,
        SettlePaymentRequest,
        SettlePaymentResponse,
        PaymentDetails,
        TreasuryPayment,
        RecipientPayment,
        PaymentToken,
    )),
    tags(
        (name = "Health", description = "Health check endpoints"),
        (name = "Settlement", description = "Settlement service endpoints"),
        (name = "Usage Parsing", description = "Usage token parsing endpoints"),
        (name = "Payment Calculation", description = "Payment calculation endpoints"),
        (name = "Payment Execution", description = "Payment execution endpoints"),
    ),
    info(
        title = "ATP Settlement Service API",
        description = "Ultra high-performance Rust implementation of the ATP Settlement Service. Provides centralized, immutable settlement logic for handling usage token parsing, payment calculation, and Solana payment execution.",
        version = "1.0.0",
        contact(
            name = "ATP Protocol",
        ),
    ),
    servers(
        (url = "http://localhost:8001", description = "Local development server"),
        (url = "https://api.example.com", description = "Production server"),
    ),
)]
struct ApiDoc;

// API Handlers

/// Health check endpoint
///
/// Returns the health status of the ATP Settlement Service
#[utoipa::path(
    get,
    path = "/health",
    tag = "Health",
    responses(
        (status = 200, description = "Service is healthy", body = Value)
    )
)]
async fn health_check() -> Json<Value> {
    Json(json!({
        "status": "healthy",
        "service": "ATP Settlement Service",
        "version": "1.0.0"
    }))
}

/// Root endpoint - API documentation
async fn root() -> Html<&'static str> {
    Html(
        r#"
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ATP Settlement Service API</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 800px;
            width: 100%;
            padding: 40px;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 2.5em;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
        }
        .info {
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            padding: 20px;
            margin: 20px 0;
            border-radius: 5px;
        }
        .info h2 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.3em;
        }
        .endpoints {
            margin: 30px 0;
        }
        .endpoint {
            background: #f8f9fa;
            padding: 15px;
            margin: 10px 0;
            border-radius: 8px;
            border-left: 3px solid #667eea;
        }
        .endpoint-method {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 0.85em;
            margin-right: 10px;
        }
        .get { background: #28a745; color: white; }
        .post { background: #007bff; color: white; }
        .endpoint-path {
            font-family: 'Courier New', monospace;
            color: #333;
            font-weight: 500;
        }
        .links {
            margin-top: 30px;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }
        .link-button {
            display: inline-block;
            padding: 12px 24px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 500;
            transition: background 0.3s;
        }
        .link-button:hover {
            background: #5568d3;
        }
        .link-button.secondary {
            background: #6c757d;
        }
        .link-button.secondary:hover {
            background: #5a6268;
        }
        .version {
            color: #999;
            font-size: 0.9em;
            margin-top: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 ATP Settlement Service</h1>
        <p class="subtitle">Ultra High-Performance Rust Implementation</p>
        
        <div class="info">
            <h2>About</h2>
            <p>This service provides a centralized, immutable settlement API that handles:</p>
            <ul style="margin-left: 20px; margin-top: 10px;">
                <li>Usage token parsing from various API formats (OpenAI, Anthropic, Google/Gemini, Cohere)</li>
                <li>Payment amount calculation with real-time token prices</li>
                <li>Solana payment execution with automatic fee splitting</li>
                <li>Settlement verification</li>
            </ul>
        </div>

        <div class="endpoints">
            <h2 style="margin-bottom: 15px; color: #333;">API Endpoints</h2>
            
            <div class="endpoint">
                <span class="endpoint-method get">GET</span>
                <span class="endpoint-path">/health</span>
                <p style="margin-top: 8px; color: #666;">Health check endpoint</p>
            </div>
            
            <div class="endpoint">
                <span class="endpoint-method post">POST</span>
                <span class="endpoint-path">/v1/settlement/parse-usage</span>
                <p style="margin-top: 8px; color: #666;">Parse usage tokens from various API formats</p>
            </div>
            
            <div class="endpoint">
                <span class="endpoint-method post">POST</span>
                <span class="endpoint-path">/v1/settlement/calculate-payment</span>
                <p style="margin-top: 8px; color: #666;">Calculate payment amounts from usage data</p>
            </div>
            
            <div class="endpoint">
                <span class="endpoint-method post">POST</span>
                <span class="endpoint-path">/v1/settlement/settle</span>
                <p style="margin-top: 8px; color: #666;">Execute settlement payment on Solana</p>
            </div>
        </div>

        <div class="links">
            <a href="/swagger-ui/" class="link-button">📚 Interactive API Docs (Swagger UI)</a>
            <a href="/openapi.json" class="link-button secondary">📄 OpenAPI JSON Schema</a>
        </div>

        <div class="version">
            Version 1.0.0 | Built with Rust & Axum
        </div>
    </div>
</body>
</html>
    "#,
    )
}

/// Parse usage tokens from various API formats
///
/// Supports multiple formats:
/// - OpenAI: prompt_tokens, completion_tokens, total_tokens
/// - Anthropic: input_tokens, output_tokens, total_tokens
/// - Google/Gemini: promptTokenCount, candidatesTokenCount, totalTokenCount
/// - Cohere: tokens, input_tokens, output_tokens
/// - Nested formats: usage.usage, meta.usage, statistics
#[utoipa::path(
    post,
    path = "/v1/settlement/parse-usage",
    tag = "Usage Parsing",
    request_body = ParseUsageRequest,
    responses(
        (status = 200, description = "Successfully parsed usage tokens", body = ParseUsageResponse),
        (status = 400, description = "Invalid request")
    )
)]
async fn parse_usage_endpoint(
    Json(request): Json<ParseUsageRequest>,
) -> Result<Json<ParseUsageResponse>, StatusCode> {
    let (input_tokens, output_tokens, total_tokens) = parse_usage_tokens(&request.usage_data);
    Ok(Json(ParseUsageResponse {
        input_tokens,
        output_tokens,
        total_tokens,
    }))
}

/// Calculate payment amounts from usage data
///
/// Calculates payment amounts based on token counts and pricing rates.
/// Fetches current token prices and computes payment amounts in the specified token (SOL or USDC).
/// Returns detailed pricing breakdown including input/output costs and payment amounts.
#[utoipa::path(
    post,
    path = "/v1/settlement/calculate-payment",
    tag = "Payment Calculation",
    request_body = CalculatePaymentRequest,
    responses(
        (status = 200, description = "Payment calculation result", body = CalculatePaymentResponse),
        (status = 500, description = "Internal server error")
    )
)]
async fn calculate_payment_endpoint(
    State(state): State<AppState>,
    Json(request): Json<CalculatePaymentRequest>,
) -> Result<Json<CalculatePaymentResponse>, (StatusCode, String)> {
    match calculate_payment_from_usage(
        &request.usage,
        request.input_cost_per_million_usd,
        request.output_cost_per_million_usd,
        request.payment_token,
        &state.price_fetcher,
        state.config.settlement_fee_percent,
    )
    .await
    {
        Ok(response) => Ok(Json(response)),
        Err(e) => Err((StatusCode::INTERNAL_SERVER_ERROR, e.to_string())),
    }
}

/// Execute settlement payment on Solana blockchain
///
/// Executes a complete settlement payment that calculates payment amounts from usage data
/// and executes a split payment transaction sending funds to both the treasury (processing fee)
/// and the recipient agent (net payment).
///
/// **WARNING**: This endpoint requires the payer's private key and performs custodial-like behavior.
/// The private key is used in-memory only and is never persisted.
#[utoipa::path(
    post,
    path = "/v1/settlement/settle",
    tag = "Payment Execution",
    request_body = SettlePaymentRequest,
    responses(
        (status = 200, description = "Settlement execution result", body = SettlePaymentResponse),
        (status = 500, description = "Internal server error")
    )
)]
async fn settle_endpoint(
    State(state): State<AppState>,
    Json(request): Json<SettlePaymentRequest>,
) -> Result<Json<SettlePaymentResponse>, (StatusCode, String)> {
    match execute_settlement(
        &request.private_key,
        &request.usage,
        request.input_cost_per_million_usd,
        request.output_cost_per_million_usd,
        &request.recipient_pubkey,
        request.payment_token,
        request.treasury_pubkey.as_deref(),
        request.skip_preflight,
        &request.commitment,
        &state,
    )
    .await
    {
        Ok(response) => Ok(Json(response)),
        Err(e) => Err((StatusCode::INTERNAL_SERVER_ERROR, e.to_string())),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::fmt::init();

    let config = Config::from_env();
    let price_fetcher = Arc::new(TokenPriceFetcher::new());

    let state = AppState {
        config,
        price_fetcher,
    };

    // Build main API router with state
    let api_router = Router::new()
        .route("/", get(root))
        .route("/health", get(health_check))
        .route("/v1/settlement/parse-usage", post(parse_usage_endpoint))
        .route(
            "/v1/settlement/calculate-payment",
            post(calculate_payment_endpoint),
        )
        .route("/v1/settlement/settle", post(settle_endpoint))
        .layer(
            ServiceBuilder::new()
                .layer(CorsLayer::permissive())
                .into_inner(),
        )
        .with_state(state);

    // Build SwaggerUI router (no state needed) - it handles /openapi.json automatically
    let swagger_router: Router = SwaggerUi::new("/swagger-ui")
        .url("/openapi.json", ApiDoc::openapi())
        .into();

    // Merge both routers
    let app = api_router.merge(swagger_router);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:8001").await?;
    info!("ATP Settlement Service listening on http://0.0.0.0:8001");

    axum::serve(listener, app).await?;

    Ok(())
}
