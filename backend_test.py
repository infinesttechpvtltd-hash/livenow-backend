import requests
import sys
from datetime import datetime

class FitTrackCoachAPITester:
    def __init__(self, base_url="https://coach-preview-6.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def run_test(self, name, method, endpoint, expected_status, data=None):
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                if response.content:
                    try:
                        resp_json = response.json()
                        print(f"   Response: {resp_json}")
                    except:
                        print(f"   Response: {response.text[:200]}")
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                self.failed_tests.append({
                    "test": name,
                    "expected": expected_status,
                    "actual": response.status_code,
                    "response": response.text[:200]
                })

            return success, response.json() if success and response.content else {}

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            self.failed_tests.append({
                "test": name,
                "error": str(e)
            })
            return False, {}

    def test_root_endpoint(self):
        """Test GET /api/"""
        success, response = self.run_test(
            "Root API endpoint",
            "GET",
            "api/",
            200
        )
        return success

    def test_subscribe_valid_email(self):
        """Test POST /api/subscribe with valid email"""
        test_email = f"test_{datetime.now().strftime('%H%M%S')}@example.com"
        success, response = self.run_test(
            "Subscribe with valid email",
            "POST",
            "api/subscribe",
            200,
            data={"email": test_email}
        )
        return success and response.get('ok') == True

    def test_subscribe_invalid_email(self):
        """Test POST /api/subscribe with invalid email"""
        success, response = self.run_test(
            "Subscribe with invalid email",
            "POST",
            "api/subscribe",
            400,
            data={"email": "invalid-email"}
        )
        return success

    def test_contact_valid_data(self):
        """Test POST /api/contact with valid data"""
        success, response = self.run_test(
            "Contact with valid data",
            "POST",
            "api/contact",
            200,
            data={
                "name": "Test User",
                "email": f"test_{datetime.now().strftime('%H%M%S')}@example.com",
                "message": "This is a test message from automated testing."
            }
        )
        return success and response.get('ok') == True

    def test_contact_invalid_data(self):
        """Test POST /api/contact with invalid data"""
        success, response = self.run_test(
            "Contact with invalid data (short name)",
            "POST",
            "api/contact",
            400,
            data={
                "name": "A",  # Too short
                "email": "test@example.com",
                "message": "Test message"
            }
        )
        return success

def main():
    print("🚀 Starting FitTrackCoach API Tests...")
    tester = FitTrackCoachAPITester()

    # Run all tests
    tests = [
        tester.test_root_endpoint,
        tester.test_subscribe_valid_email,
        tester.test_subscribe_invalid_email,
        tester.test_contact_valid_data,
        tester.test_contact_invalid_data,
    ]

    for test in tests:
        test()

    # Print results
    print(f"\n📊 Test Results:")
    print(f"   Tests passed: {tester.tests_passed}/{tester.tests_run}")
    print(f"   Success rate: {(tester.tests_passed/tester.tests_run)*100:.1f}%")
    
    if tester.failed_tests:
        print(f"\n❌ Failed tests:")
        for failure in tester.failed_tests:
            if 'error' in failure:
                print(f"   - {failure['test']}: {failure['error']}")
            else:
                print(f"   - {failure['test']}: Expected {failure.get('expected')}, got {failure.get('actual')}")

    return 0 if tester.tests_passed == tester.tests_run else 1

if __name__ == "__main__":
    sys.exit(main())