"""Unit tests for CLI prompts, utilities, and diagnostics."""

import unittest
from dns_expert.prompt import build_rag_prompt
from dns_expert.utils import detect_input_type


class TestCLIUtilities(unittest.TestCase):
    def test_input_type_detection(self):
        dig_sample = """;; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 12345
;; flags: qr rd ra; QUERY: 1, ANSWER: 0, AUTHORITY: 1, ADDITIONAL: 1
"""
        self.assertEqual(detect_input_type(dig_sample), "dig_output")

        bind_sample = """zone "example.org" {
    type slave;
    masters { 192.0.2.1; };
};"""
        self.assertEqual(detect_input_type(bind_sample), "bind_config")

    def test_rag_prompt_assembly(self):
        sources = [
            {
                "citation_label": "[RFC 1035 | Section 3.2.1]",
                "content": "MX records specify a mail exchanger for a domain name.",
            }
        ]
        messages = build_rag_prompt("What is an MX record?", sources)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("RFC 1035", messages[1]["content"])
        self.assertIn("What is an MX record?", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
