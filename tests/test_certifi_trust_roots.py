"""The real web consumer must not trust the compromised emSign ECC G3 root.

Source: https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2
The publisher recommends2026.10.19 to retain unaffected emSign roots.
"""

import ssl

import certifi

from tools import web_ingest


def test_web_consumer_excludes_compromised_emsign_root():
    context = web_ingest._ssl_context()
    names = {
        value
        for certificate in context.get_ca_certs()
        for part in certificate["subject"]
        for key, value in part
        if key == "commonName"
    }
    assert "emSign ECC Root CA - G3" not in names
    expected = ssl.create_default_context(cafile=certifi.where())
    assert set(context.get_ca_certs(binary_form=True)) == set(
        expected.get_ca_certs(binary_form=True)
    )
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
