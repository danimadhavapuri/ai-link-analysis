import subprocess
import csv
import sys

def run_tests():
    print("Running 37 test cases...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_link_analysis.py", "-v", "--tb=no"],
        capture_output=True,
        text=True
    )
    
    lines = result.stdout.splitlines()
    test_rows = []
    
    for line in lines:
        if "::" in line and ("PASSED" in line or "FAILED" in line):
            parts = line.split("::")
            file_name = parts[0].strip()
            class_and_test = parts[1].split()
            test_full = class_and_test[0]
            status = "PASSED" if "PASSED" in line else "FAILED"
            
            # Category extraction
            category = "General"
            if "TestSSRFProtection" in test_full:
                category = "SSRF Protection & URL Validation"
            elif "TestHTMLExtraction" in test_full:
                category = "HTML Extraction & Noise Filtering"
            elif "TestSchemaValidation" in test_full:
                category = "Pydantic Schema Validation"
            elif "TestAPIEndpoints" in test_full:
                category = "FastAPI Endpoints & Error Handling"
                
            test_name = test_full.split(".")[-1]
            test_rows.append({
                "Test ID": len(test_rows) + 1,
                "Category": category,
                "Test Case": test_name,
                "Status": status
            })

    # Save CSV for Google Sheets
    csv_file = "test_results.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Test ID", "Category", "Test Case", "Status"])
        writer.writeheader()
        writer.writerows(test_rows)

    # Save Markdown for Google Docs
    md_file = "test_results.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# Automated Test Execution Report\n\n")
        f.write(f"**Total Tests:** {len(test_rows)} | **Passed:** {sum(1 for r in test_rows if r['Status'] == 'PASSED')} | **Failed:** {sum(1 for r in test_rows if r['Status'] == 'FAILED')}\n\n")
        f.write("| Test ID | Category | Test Case | Status |\n")
        f.write("|---------|----------|-----------|--------|\n")
        for r in test_rows:
            badge = "✅ PASSED" if r["Status"] == "PASSED" else "❌ FAILED"
            f.write(f"| {r['Test ID']} | {r['Category']} | `{r['Test Case']}` | {badge} |\n")

    print(f"Generated {csv_file} (for Google Sheets)")
    print(f"Generated {md_file} (for Google Docs)")
    print(f"Total Tests Executed: {len(test_rows)} | All Passed: {all(r['Status'] == 'PASSED' for r in test_rows)}")

if __name__ == "__main__":
    run_tests()
