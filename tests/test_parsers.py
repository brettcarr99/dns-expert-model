"""Unit tests for RFC, Vendor Doc, and Mail parsers."""

import tempfile
import unittest
from pathlib import Path

from dns_expert.knowledge.parsers.doc_parser import DocParser
from dns_expert.knowledge.parsers.mail_parser import MailParser
from dns_expert.knowledge.parsers.rfc_parser import RFCParser


class TestParsers(unittest.TestCase):
    def test_rfc_parser_chunking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rfc_dir = Path(tmpdir)
            sample_rfc = rfc_dir / "rfc8484.txt"
            sample_rfc.write_text(
                """Network Working Group                                     P. Hoffman
Request for Comments: 8484                                ICANN
Category: Standards Track                                  P. McManus
                                                          Mozilla
                                                     October 2018

          DNS Queries over HTTPS (DoH)

Abstract
   This document defines a protocol for sending DNS queries and getting
   DNS responses over HTTPS.

1.  Introduction
   This document describes a focused protocol for sending DNS queries and
   getting DNS responses over HTTPS (DoH).

2.  Protocol Description
   A DNS client sends a DNS query using HTTP POST or GET.
"""
            )
            parser = RFCParser(rfc_dir)
            chunks = list(parser.parse_all())
            self.assertGreaterEqual(len(chunks), 1)
            self.assertEqual(chunks[0]["source_type"], "rfc")
            self.assertEqual(chunks[0]["source_id"], "rfc8484")
            self.assertIn("DoH", chunks[0]["title"])

    def test_doc_parser(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            vendor_dir = Path(tmpdir) / "bind9"
            vendor_dir.mkdir()
            doc_file = vendor_dir / "zones.rst"
            doc_file.write_text(
                """Zone Statement Grammar
======================

The `zone` statement is used to define a DNS zone.

.. code-block:: bind

   zone "example.com" {
       type master;
       file "example.com.db";
   };
"""
            )
            parser = DocParser(Path(tmpdir))
            chunks = list(parser.parse_all())
            self.assertGreaterEqual(len(chunks), 1)
            self.assertEqual(chunks[0]["vendor"], "bind9")
            self.assertIn("zone \"example.com\"", chunks[0]["content"])

    def test_mail_parser(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            list_dir = Path(tmpdir) / "ietf" / "dnsop"
            list_dir.mkdir(parents=True)
            eml_file = list_dir / "msg1.eml"
            eml_file.write_text(
                """From: alice@example.com
To: dnsop@ietf.org
Subject: [DNSOP] Question on DS Record TTL
Date: Wed, 15 May 2024 10:00:00 +0000
Message-ID: <msg1@example.com>

Hi DNSOP,

What is the recommended TTL for parent DS records?

Thanks,
Alice
"""
            )
            parser = MailParser(Path(tmpdir))
            chunks = list(parser.parse_all())
            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0]["source_type"], "discussion")
            self.assertIn("DS Record TTL", chunks[0]["title"])


if __name__ == "__main__":
    unittest.main()
