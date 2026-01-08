#!/usr/bin/env python3
"""
ATP Settlement Service API Test Script

Test all endpoints of the ATP Settlement Service.
Make sure the service is running on http://localhost:8001
"""

import json
import requests

BASE_URL = "http://localhost:8001"


def print_response(title: str, response: requests.Response):
    """Pretty print API response."""
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    print(f"Status: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except:
        print(f"Response: {response.text}")
    print()


def test_health_check():
    """Test health check endpoint."""
    response = requests.get(f"{BASE_URL}/health")
    print_response("1. Health Check", response)
    return response.status_code == 200


def test_parse_usage_openai():
    """Test parse usage with OpenAI format."""
    data = {
        "usage_data": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    }
    response = requests.post(
        f"{BASE_URL}/v1/settlement/parse-usage",
        json=data
    )
    print_response("2. Parse Usage (OpenAI Format)", response)
    return response.status_code == 200


def test_parse_usage_anthropic():
    """Test parse usage with Anthropic format."""
    data = {
        "usage_data": {
            "input_tokens": 200,
            "output_tokens": 100,
            "total_tokens": 300
        }
    }
    response = requests.post(
        f"{BASE_URL}/v1/settlement/parse-usage",
        json=data
    )
    print_response("3. Parse Usage (Anthropic Format)", response)
    return response.status_code == 200


def test_parse_usage_gemini():
    """Test parse usage with Google/Gemini format."""
    data = {
        "usage_data": {
            "promptTokenCount": 150,
            "candidatesTokenCount": 75,
            "totalTokenCount": 225
        }
    }
    response = requests.post(
        f"{BASE_URL}/v1/settlement/parse-usage",
        json=data
    )
    print_response("4. Parse Usage (Google/Gemini Format)", response)
    return response.status_code == 200


def test_calculate_payment_sol():
    """Test calculate payment with SOL."""
    data = {
        "usage": {
            "input_tokens": 1000,
            "output_tokens": 500,
            "total_tokens": 1500
        },
        "input_cost_per_million_usd": 2.50,
        "output_cost_per_million_usd": 10.00,
        "payment_token": "SOL"
    }
    response = requests.post(
        f"{BASE_URL}/v1/settlement/calculate-payment",
        json=data
    )
    print_response("5. Calculate Payment (SOL)", response)
    return response.status_code == 200


def test_calculate_payment_usdc():
    """Test calculate payment with USDC."""
    data = {
        "usage": {
            "input_tokens": 2000,
            "output_tokens": 1000,
            "total_tokens": 3000
        },
        "input_cost_per_million_usd": 5.00,
        "output_cost_per_million_usd": 15.00,
        "payment_token": "USDC"
    }
    response = requests.post(
        f"{BASE_URL}/v1/settlement/calculate-payment",
        json=data
    )
    print_response("6. Calculate Payment (USDC)", response)
    return response.status_code == 200


def test_calculate_payment_zero_cost():
    """Test calculate payment with zero cost (should be skipped)."""
    data = {
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        },
        "input_cost_per_million_usd": 2.50,
        "output_cost_per_million_usd": 10.00,
        "payment_token": "SOL"
    }
    response = requests.post(
        f"{BASE_URL}/v1/settlement/calculate-payment",
        json=data
    )
    print_response("7. Calculate Payment (Zero Cost - Should Skip)", response)
    return response.status_code == 200


def test_settle_payment_example():
    """Example settle payment request (DO NOT USE REAL PRIVATE KEYS)."""
    print("\n" + "="*60)
    print("8. Settle Payment (Example - DO NOT USE REAL KEYS!)")
    print("="*60)
    print("\nExample request body:")
    example_data = {
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
        "treasury_pubkey": None,
        "skip_preflight": False,
        "commitment": "confirmed"
    }
    print(json.dumps(example_data, indent=2))
    print("\n⚠️  WARNING: This endpoint requires a real private key.")
    print("⚠️  Only use testnet/devnet keys for testing!")
    print("⚠️  Never use production keys!")
    print()


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("ATP Settlement Service API Test Suite")
    print("="*60)
    print(f"Testing service at: {BASE_URL}")
    print("\nMake sure the service is running before executing tests!")
    
    try:
        # Test health check first
        if not test_health_check():
            print("❌ Health check failed! Is the service running?")
            return
        
        # Run all tests
        tests = [
            ("Parse Usage (OpenAI)", test_parse_usage_openai),
            ("Parse Usage (Anthropic)", test_parse_usage_anthropic),
            ("Parse Usage (Gemini)", test_parse_usage_gemini),
            ("Calculate Payment (SOL)", test_calculate_payment_sol),
            ("Calculate Payment (USDC)", test_calculate_payment_usdc),
            ("Calculate Payment (Zero Cost)", test_calculate_payment_zero_cost),
        ]
        
        results = []
        for name, test_func in tests:
            try:
                success = test_func()
                results.append((name, success))
            except Exception as e:
                print(f"❌ Error in {name}: {e}")
                results.append((name, False))
        
        # Show settle payment example (don't actually call it)
        test_settle_payment_example()
        
        # Summary
        print("\n" + "="*60)
        print("Test Summary")
        print("="*60)
        for name, success in results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"{status}: {name}")
        
        all_passed = all(success for _, success in results)
        if all_passed:
            print("\n🎉 All tests passed!")
        else:
            print("\n⚠️  Some tests failed. Check the output above.")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ Connection Error!")
        print("Make sure the ATP Settlement Service is running on http://localhost:8001")
        print("\nStart the service with:")
        print("  cd rust_settlement_api")
        print("  cargo run --release")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()

