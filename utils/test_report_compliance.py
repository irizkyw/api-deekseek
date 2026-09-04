"""
Unit tests for verifying strict compliance with .agents/skills/report-executive.md
"""

import unittest
from pathlib import Path
from utils.report_generator import generate_executive_reports


class TestReportExecutiveCompliance(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.target = "geolocsys.azuba.tech"

    def test_report_generation_and_headers(self):
        pentest_path, bounty_path = generate_executive_reports(self.target, self.base_dir)

        p_file = Path(pentest_path)
        b_file = Path(bounty_path)

        self.assertTrue(p_file.exists(), "Pentest report file must exist")
        self.assertTrue(b_file.exists(), "Bounty report file must exist")

        p_content = p_file.read_text(encoding="utf-8")
        b_content = b_file.read_text(encoding="utf-8")

        # 1. Size checks (must not be truncated or empty)
        self.assertGreater(len(p_content), 5000, "Pentest report must be comprehensive (>5000 chars)")
        self.assertGreater(len(b_content), 1500, "Bounty report must be detailed (>1500 chars)")

        # 2. Executive Summary checks
        self.assertIn("# Security Assessment Report", p_content)
        self.assertIn("## Executive Summary", p_content)
        self.assertIn("Target:", p_content)
        self.assertIn("Assessment Date:", p_content)
        self.assertIn("Scope:", p_content)

        # 3. All 8 Vulnerability Categories in Pentest Summary
        required_categories = [
            "**Authentication Vulnerabilities:**",
            "**Authorization Vulnerabilities:**",
            "**Cross-Site Scripting (XSS) Vulnerabilities:**",
            "**SQL/Command Injection Vulnerabilities:**",
            "**Server-Side Request Forgery (SSRF) Vulnerabilities:**",
            "**Business Logic Vulnerabilities:**",
            "**Other Vulnerabilities:**",
            "**Potential Vulnerabilities:**",
        ]
        for cat in required_categories:
            self.assertIn(cat, p_content, f"Category '{cat}' must be present in Pentest summary")

        # 4. Network Reconnaissance Section
        self.assertIn("## Network Reconnaissance", p_content)

        # 5. Exploitation Evidence & Burp-ready HTTP blocks
        self.assertIn("RISK LEVEL:", p_content)
        self.assertIn("CVSS 4.0:", p_content)
        self.assertIn("Step of Discovery (POC):", p_content)
        self.assertIn("```http", p_content)

        # 6. Bounty Golden Rule note & filters
        self.assertIn('If I mass-report this to 100 different bug bounty programs, how many would PAY me for it?', b_content)
        self.assertIn('## Executive Summary', b_content)

        # 7. Mirroring checks in deliverables/
        deliv_p = self.base_dir / "deliverables" / "comprehensive_security_assessment_report.md"
        deliv_b = self.base_dir / "deliverables" / "comprehensive_security_assessment_report_bounty.md"
        self.assertTrue(deliv_p.exists(), "Deliverables pentest report must be mirrored")
        self.assertTrue(deliv_b.exists(), "Deliverables bounty report must be mirrored")


if __name__ == "__main__":
    unittest.main()
