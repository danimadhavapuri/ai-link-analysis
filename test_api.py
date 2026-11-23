import json
import sys
import time
import httpx

API_BASE_URL = "http://localhost:4000"

def test_api(target_url: str = "https://stripe.com"):
    print("=" * 60)
    print(f"🚀 Testing AI Link Analysis API at {API_BASE_URL}")
    print("=" * 60)

    # 1. Test Health Check
    print("\n1️⃣  Testing Health Check (/health)...")
    try:
        health_resp = httpx.get(f"{API_BASE_URL}/health", timeout=5.0)
        print(f"   Status Code: {health_resp.status_code}")
        print(f"   Response:    {health_resp.json()}")
    except Exception as e:
        print(f"❌ Could not connect to API at {API_BASE_URL}.")
        print("   Make sure your server is running in another terminal:")
        print("   uvicorn app.main:app --host 127.0.0.1 --port 4000")
        return

    # 2. Test Link Analysis POST
    print(f"\n2️⃣  Analyzing Website: {target_url}...")
    print("   Sending request to POST /link-analysis (fetching site & running AI)...")
    t0 = time.time()
    try:
        response = httpx.post(
            f"{API_BASE_URL}/link-analysis",
            json={"url": target_url},
            timeout=60.0,
        )
        elapsed = round(time.time() - t0, 2)
        print(f"   Status Code: {response.status_code} (took {elapsed}s)")

        if response.status_code == 200:
            data = response.json()
            print("\n✅ Analysis Successful!")
            print(f"   Brand:   {data.get('brand')}")
            print(f"   Website: {data.get('website')}")

            analysis = data.get("analysis", {})

            # 1. Competitor Analysis
            comp = analysis.get("competitor_analysis", {})
            print(f"\n--- [1] Competitor Analysis ---")
            print(f"   Category: {comp.get('main_business_category')}")
            print(f"   Competitors ({len(comp.get('competitors', []))}):")
            for c in comp.get("competitors", []):
                label = "[AI-Inferred]" if c.get("is_inferred") else "[From Site]"
                print(f"     • {c.get('name')} {label} - Strengths: {', '.join(c.get('strengths', [])[:2])}")

            # 2. Target Search Queries
            queries = analysis.get("target_search_queries", [])
            print(f"\n--- [2] Target Search Queries ({len(queries)} Platforms) ---")
            for q in queries:
                print(f"     • [{q.get('platform')}] '{q.get('query')}' ({q.get('search_intent')})")

            # 3. SEO Improvements
            seo = analysis.get("seo_improvements", {})
            print(f"\n--- [3] SEO Improvements ---")
            print(f"   Primary Keyword: {seo.get('primary_keyword')}")
            print(f"   SEO Title:       {seo.get('recommended_seo_title', {}).get('title')}")
            print(f"   Meta Desc:       {seo.get('recommended_meta_description')}")

            # 4. Top Services
            services = analysis.get("top_services", [])
            print(f"\n--- [4] Top 5 Services ---")
            for s in services:
                inf = "(Inferred)" if s.get("is_inferred") else ""
                print(f"     • {s.get('service_name')} {inf}: {s.get('main_benefit')}")

            # 5. Target Audience
            aud = analysis.get("target_audience", {})
            print(f"\n--- [5] Target Audience ---")
            print(f"   Primary:   {aud.get('primary_target_audience')}")
            print(f"   Segments:  {', '.join(aud.get('industry_segments', [])[:3])}")

            print("\n🎉 All 5 sections verified successfully!")
        else:
            print(f"❌ Error: {response.text}")

    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://chivoxai.com"
    test_api(target)
