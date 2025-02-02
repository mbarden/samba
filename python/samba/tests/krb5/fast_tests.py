#!/usr/bin/env python3
# Unix SMB/CIFS implementation.
# Copyright (C) Stefan Metzmacher 2020
# Copyright (C) 2020 Catalyst.Net Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import functools
import os
import sys

import ldb

from samba.dcerpc import security
from samba.tests.krb5.raw_testcase import (
    KerberosTicketCreds,
    Krb5EncryptionKey
)
from samba.tests.krb5.kdc_base_test import KDCBaseTest
from samba.tests.krb5.rfc4120_constants import (
    AD_FX_FAST_ARMOR,
    AD_FX_FAST_USED,
    AES256_CTS_HMAC_SHA1_96,
    ARCFOUR_HMAC_MD5,
    FX_FAST_ARMOR_AP_REQUEST,
    KDC_ERR_ETYPE_NOSUPP,
    KDC_ERR_GENERIC,
    KDC_ERR_NOT_US,
    KDC_ERR_PREAUTH_FAILED,
    KDC_ERR_PREAUTH_REQUIRED,
    KDC_ERR_UNKNOWN_CRITICAL_FAST_OPTIONS,
    KRB_AS_REP,
    KRB_TGS_REP,
    KU_AS_REP_ENC_PART,
    KU_TICKET,
    NT_PRINCIPAL,
    NT_SRV_INST,
    NT_WELLKNOWN,
    PADATA_FX_COOKIE,
    PADATA_FX_FAST,
    PADATA_PAC_OPTIONS
)
import samba.tests.krb5.rfc4120_pyasn1 as krb5_asn1
import samba.tests.krb5.kcrypto as kcrypto

sys.path.insert(0, "bin/python")
os.environ["PYTHONUNBUFFERED"] = "1"

global_asn1_print = False
global_hexdump = False


class FAST_Tests(KDCBaseTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_tgt = None
        cls.user_enc_part = None
        cls.user_service_ticket = None

        cls.mach_tgt = None
        cls.mach_enc_part = None
        cls.mach_service_ticket = None

    def setUp(self):
        super().setUp()
        self.do_asn1_print = global_asn1_print
        self.do_hexdump = global_hexdump

    def test_simple(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': False
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': False,
                'gen_padata_fn': self.generate_enc_timestamp_padata
            }
        ])

    def test_simple_tgs(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': False,
                'gen_tgt_fn': self.get_user_tgt
            }
        ])

    def test_simple_tgs_wrong_principal(self):
        mach_creds = self.get_mach_creds()
        mach_name = mach_creds.get_username()
        expected_cname = self.PrincipalName_create(
            name_type=NT_PRINCIPAL, names=[mach_name])

        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': False,
                'gen_tgt_fn': self.get_mach_tgt,
                'expected_cname': expected_cname
            }
        ])

    def test_simple_tgs_service_ticket(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_NOT_US,
                'use_fast': False,
                'gen_tgt_fn': self.get_user_service_ticket,
            }
        ])

    def test_simple_tgs_service_ticket_mach(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_NOT_US,
                'use_fast': False,
                'gen_tgt_fn': self.get_mach_service_ticket,
            }
        ])

    def test_fast_no_claims(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'pac_options': '0'
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'pac_options': '0'
            }
        ])

    def test_fast_tgs_no_claims(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'pac_options': '0'
            }
        ])

    def test_fast_no_claims_or_canon(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'pac_options': '0',
                'kdc_options': '0'
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'pac_options': '0',
                'kdc_options': '0'
            }
        ])

    def test_fast_tgs_no_claims_or_canon(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'pac_options': '0',
                'kdc_options': '0'
            }
        ])

    def test_fast_no_canon(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'kdc_options': '0'
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'kdc_options': '0'
            }
        ])

    def test_fast_tgs_no_canon(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'kdc_options': '0'
            }
        ])

    def test_simple_tgs_no_etypes(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_ETYPE_NOSUPP,
                'use_fast': False,
                'gen_tgt_fn': self.get_mach_tgt,
                'etypes': ()
            }
        ])

    def test_fast_tgs_no_etypes(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_ETYPE_NOSUPP,
                'use_fast': True,
                'gen_tgt_fn': self.get_mach_tgt,
                'fast_armor': None,
                'etypes': ()
            }
        ])

    def test_simple_no_etypes(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_ETYPE_NOSUPP,
                'use_fast': False,
                'etypes': ()
            }
        ])

    def test_simple_fast_no_etypes(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_ETYPE_NOSUPP,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'etypes': ()
            }
        ])

    def test_empty_fast(self):
        # Add an empty PA-FX-FAST in the initial AS-REQ. This should get
        # rejected with a Generic error.
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_GENERIC,
                'use_fast': True,
                'gen_fast_fn': self.generate_empty_fast,
                'fast_armor': None,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_unknown_critical_option(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_UNKNOWN_CRITICAL_FAST_OPTIONS,
                'use_fast': True,
                'fast_options': '001',  # unsupported critical option
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_unarmored_as_req(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_GENERIC,
                'use_fast': True,
                'fast_armor': None,  # no armor,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_invalid_armor_type(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_FAILED,
                'use_fast': True,
                'fast_armor': 0,  # invalid armor type
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_invalid_armor_type2(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_FAILED,
                'use_fast': True,
                'fast_armor': 2,  # invalid armor type
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_encrypted_challenge(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_encrypted_challenge_wrong_key(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_FAILED,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata_wrong_key,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_encrypted_challenge_wrong_key_kdc(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_FAILED,
                'use_fast': True,
                'gen_padata_fn':
                self.generate_enc_challenge_padata_wrong_key_kdc,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_encrypted_challenge_clock_skew(self):
        # The KDC is supposed to confirm that the timestamp is within its
        # current clock skew, and return KRB_APP_ERR_SKEW if it is not (RFC6113
        # 5.4.6).  However, Windows accepts a skewed timestamp in the encrypted
        # challenge.
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': functools.partial(
                    self.generate_enc_challenge_padata,
                    skew=10000),
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_invalid_tgt(self):
        # The armor ticket 'sname' field is required to identify the target
        # realm TGS (RFC6113 5.4.1.1). However, Windows will still accept a
        # service ticket identifying a different server principal.
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_user_service_ticket
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_user_service_ticket
                                    # ticket not identifying TGS of current
                                    # realm
            }
        ])

    def test_fast_invalid_tgt_mach(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_service_ticket
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_service_ticket
                                    # ticket not identifying TGS of current
                                    # realm
            }
        ])

    def test_fast_enc_timestamp(self):
        # Provide ENC-TIMESTAMP as FAST padata when we should be providing
        # ENCRYPTED-CHALLENGE - ensure that we get PREAUTH_REQUIRED.
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_timestamp_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_tgs(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None
            }
        ])

    def test_fast_tgs_armor(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST
            }
        ])

    def test_fast_outer_wrong_realm(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'realm': 'TEST'  # should be ignored
                }
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'realm': 'TEST'  # should be ignored
                }
            }
        ])

    def test_fast_tgs_outer_wrong_realm(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'outer_req': {
                    'realm': 'TEST'  # should be ignored
                }
            }
        ])

    def test_fast_outer_wrong_nonce(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'nonce': '123'  # should be ignored
                }
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'nonce': '123'  # should be ignored
                }
            }
        ])

    def test_fast_tgs_outer_wrong_nonce(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'outer_req': {
                    'nonce': '123'  # should be ignored
                }
            }
        ])

    def test_fast_outer_wrong_flags(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'kdc-options': '11111111111111111'  # should be ignored
                }
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'kdc-options': '11111111111111111'  # should be ignored
                }
            }
        ])

    def test_fast_tgs_outer_wrong_flags(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'outer_req': {
                    'kdc-options': '11111111111111111'  # should be ignored
                }
            }
        ])

    def test_fast_outer_wrong_till(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'till': '15000101000000Z'  # should be ignored
                }
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'outer_req': {
                    'till': '15000101000000Z'  # should be ignored
                }
            }
        ])

    def test_fast_tgs_outer_wrong_till(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'outer_req': {
                    'till': '15000101000000Z'  # should be ignored
                }
            }
        ])

    def test_fast_authdata_fast_used(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_authdata_fn': self.generate_fast_used_auth_data,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None
            }
        ])

    def test_fast_authdata_fast_not_used(self):
        # The AD-fx-fast-used authdata type can be included in the
        # authenticator or the TGT authentication data to indicate that FAST
        # must be used. The KDC must return KRB_APP_ERR_MODIFIED if it receives
        # this authdata type in a request not using FAST (RFC6113 5.4.2).
        self._run_test_sequence([
            # This request works without FAST.
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': False,
                'gen_tgt_fn': self.get_user_tgt
            },
            # Add the 'FAST used' auth data and it now fails.
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_GENERIC,
                # should be KRB_APP_ERR_MODIFIED
                'use_fast': False,
                'gen_authdata_fn': self.generate_fast_used_auth_data,
                'gen_tgt_fn': self.get_user_tgt
            }
        ])

    def test_fast_ad_fx_fast_armor(self):
        # If the authenticator or TGT authentication data contains the
        # AD-fx-fast-armor authdata type, the KDC must reject the request
        # (RFC6113 5.4.1.1).
        self._run_test_sequence([
            # This request works.
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None
            },
            # Add the 'FAST armor' auth data and it now fails.
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_GENERIC,
                'use_fast': True,
                'gen_authdata_fn': self.generate_fast_armor_auth_data,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None
            }
        ])

    def test_fast_ad_fx_fast_armor2(self):
        # Show that we can still use the AD-fx-fast-armor authorization data in
        # FAST armor tickets.
        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'gen_authdata_fn': self.generate_fast_armor_auth_data,
                # include the auth data in the FAST armor.
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            }
        ])

    def test_fast_ad_fx_fast_armor_ticket(self):
        # If the authenticator or TGT authentication data contains the
        # AD-fx-fast-armor authdata type, the KDC must reject the request
        # (RFC6113 5.4.2).
        self._run_test_sequence([
            # This request works.
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None
            },
            # Add AD-fx-fast-armor authdata element to user TGT. This request
            # fails.
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_GENERIC,
                'use_fast': True,
                'gen_tgt_fn': self.gen_tgt_fast_armor_auth_data,
                'fast_armor': None
            }
        ])

    def test_fast_ad_fx_fast_armor_ticket2(self):
        self._run_test_sequence([
            # Show that we can still use the modified ticket as armor.
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.gen_tgt_fast_armor_auth_data
            }
        ])

    def test_fast_tgs_service_ticket(self):
        # Try to use a non-TGT ticket to establish an armor key, which fails
        # (RFC6113 5.4.2).
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_NOT_US,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_service_ticket,  # fails
                'fast_armor': None
            }
        ])

    def test_fast_tgs_service_ticket_mach(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_NOT_US,  # fails
                'use_fast': True,
                'gen_tgt_fn': self.get_mach_service_ticket,
                'fast_armor': None
            }
        ])

    def test_simple_tgs_no_subkey(self):
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': False,
                'gen_tgt_fn': self.get_user_tgt,
                'include_subkey': False
            }
        ])

    def test_fast_tgs_no_subkey(self):
        # Show that omitting the subkey in the TGS-REQ authenticator fails
        # (RFC6113 5.4.2).
        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': KDC_ERR_GENERIC,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'include_subkey': False
            }
        ])

    def test_fast_hide_client_names(self):
        user_creds = self.get_client_creds()
        user_name = user_creds.get_username()
        user_cname = self.PrincipalName_create(name_type=NT_PRINCIPAL,
                                               names=[user_name])

        expected_cname = self.PrincipalName_create(
            name_type=NT_WELLKNOWN, names=['WELLKNOWN', 'ANONYMOUS'])

        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'fast_options': '01',  # hide client names
                'expected_cname': expected_cname
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': self.generate_enc_challenge_padata,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'fast_options': '01',  # hide client names
                'expected_cname': expected_cname,
                'expected_cname_private': user_cname
            }
        ])

    def test_fast_tgs_hide_client_names(self):
        user_creds = self.get_client_creds()
        user_name = user_creds.get_username()
        user_cname = self.PrincipalName_create(name_type=NT_PRINCIPAL,
                                               names=[user_name])

        expected_cname = self.PrincipalName_create(
            name_type=NT_WELLKNOWN, names=['WELLKNOWN', 'ANONYMOUS'])

        self._run_test_sequence([
            {
                'rep_type': KRB_TGS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_tgt_fn': self.get_user_tgt,
                'fast_armor': None,
                'fast_options': '01',  # hide client names
                'expected_cname': expected_cname,
                'expected_cname_private': user_cname
            }
        ])

    def test_fast_encrypted_challenge_replay(self):
        # The KDC is supposed to check that encrypted challenges are not
        # replays (RFC6113 5.4.6), but timestamps may be reused; an encrypted
        # challenge is only considered a replay if the ciphertext is identical
        # to a previous challenge. Windows does not perform this check.

        class GenerateEncChallengePadataReplay:
            def __init__(replay):
                replay._padata = None

            def __call__(replay, key, armor_key):
                if replay._padata is None:
                    client_challenge_key = (
                        self.generate_client_challenge_key(armor_key, key))
                    replay._padata = self.get_challenge_pa_data(
                        client_challenge_key)

                return replay._padata

        self._run_test_sequence([
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': KDC_ERR_PREAUTH_REQUIRED,
                'use_fast': True,
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt
            },
            {
                'rep_type': KRB_AS_REP,
                'expected_error_mode': 0,
                'use_fast': True,
                'gen_padata_fn': GenerateEncChallengePadataReplay(),
                'fast_armor': FX_FAST_ARMOR_AP_REQUEST,
                'gen_armor_tgt_fn': self.get_mach_tgt,
                'repeat': 2
            }
        ])

    def generate_enc_timestamp_padata(self, key, _armor_key):
        return self.get_enc_timestamp_pa_data_from_key(key)

    def generate_enc_challenge_padata(self, key, armor_key, skew=0):
        client_challenge_key = (
            self.generate_client_challenge_key(armor_key, key))
        return self.get_challenge_pa_data(client_challenge_key, skew=skew)

    def generate_enc_challenge_padata_wrong_key_kdc(self, key, armor_key):
        kdc_challenge_key = (
            self.generate_kdc_challenge_key(armor_key, key))
        return self.get_challenge_pa_data(kdc_challenge_key)

    def generate_enc_challenge_padata_wrong_key(self, key, _armor_key):
        return self.get_challenge_pa_data(key)

    def generate_empty_fast(self,
                            _kdc_exchange_dict,
                            _callback_dict,
                            _req_body,
                            _fast_padata,
                            _fast_armor,
                            _checksum,
                            _fast_options=''):
        fast_padata = self.PA_DATA_create(PADATA_FX_FAST, b'')

        return fast_padata

    def _run_test_sequence(self, test_sequence):
        if self.strict_checking:
            self.check_kdc_fast_support()

        kdc_options_default = str(krb5_asn1.KDCOptions('forwardable,'
                                                       'renewable,'
                                                       'canonicalize,'
                                                       'renewable-ok'))

        pac_request = self.get_pa_pac_request()

        client_creds = self.get_client_creds()
        target_creds = self.get_service_creds()
        krbtgt_creds = self.get_krbtgt_creds()

        client_username = client_creds.get_username()
        client_realm = client_creds.get_realm()
        client_cname = self.PrincipalName_create(name_type=NT_PRINCIPAL,
                                                 names=[client_username])

        krbtgt_username = krbtgt_creds.get_username()
        krbtgt_realm = krbtgt_creds.get_realm()
        krbtgt_sname = self.PrincipalName_create(
            name_type=NT_SRV_INST, names=[krbtgt_username, krbtgt_realm])
        krbtgt_decryption_key = self.TicketDecryptionKey_from_creds(
            krbtgt_creds)

        target_username = target_creds.get_username()[:-1]
        target_realm = target_creds.get_realm()
        target_service = 'host'
        target_sname = self.PrincipalName_create(
            name_type=NT_SRV_INST, names=[target_service, target_username])
        target_decryption_key = self.TicketDecryptionKey_from_creds(
            target_creds, etype=kcrypto.Enctype.RC4)

        fast_cookie = None
        preauth_etype_info2 = None

        preauth_key = None

        for kdc_dict in test_sequence:
            rep_type = kdc_dict.pop('rep_type')
            self.assertIn(rep_type, (KRB_AS_REP, KRB_TGS_REP))

            expected_error_mode = kdc_dict.pop('expected_error_mode')
            self.assertIn(expected_error_mode, range(240))

            use_fast = kdc_dict.pop('use_fast')
            self.assertIs(type(use_fast), bool)

            if use_fast:
                self.assertIn('fast_armor', kdc_dict)
                fast_armor_type = kdc_dict.pop('fast_armor')

                if fast_armor_type is not None:
                    self.assertIn('gen_armor_tgt_fn', kdc_dict)
                elif expected_error_mode != KDC_ERR_GENERIC:
                    self.assertNotIn('gen_armor_tgt_fn', kdc_dict)

                gen_armor_tgt_fn = kdc_dict.pop('gen_armor_tgt_fn', None)
                if gen_armor_tgt_fn is not None:
                    armor_tgt = gen_armor_tgt_fn()
                else:
                    armor_tgt = None

                fast_options = kdc_dict.pop('fast_options', '')
            else:
                fast_armor_type = None
                armor_tgt = None

                self.assertNotIn('fast_options', kdc_dict)
                fast_options = None

            if rep_type == KRB_TGS_REP:
                gen_tgt_fn = kdc_dict.pop('gen_tgt_fn')
                tgt = gen_tgt_fn()
            else:
                self.assertNotIn('gen_tgt_fn', kdc_dict)
                tgt = None

            if expected_error_mode != 0:
                check_error_fn = self.generic_check_kdc_error
                check_rep_fn = None
            else:
                check_error_fn = None
                check_rep_fn = self.generic_check_kdc_rep

            etypes = kdc_dict.pop('etypes', (AES256_CTS_HMAC_SHA1_96,
                                             ARCFOUR_HMAC_MD5))

            cname = client_cname if rep_type == KRB_AS_REP else None
            crealm = client_realm

            if rep_type == KRB_AS_REP:
                sname = krbtgt_sname
                srealm = krbtgt_realm
            else:  # KRB_TGS_REP
                sname = target_sname
                srealm = target_realm

            expected_cname = kdc_dict.pop('expected_cname', client_cname)
            expected_cname_private = kdc_dict.pop('expected_cname_private',
                                                  None)
            expected_crealm = kdc_dict.pop('expected_crealm', client_realm)
            expected_sname = kdc_dict.pop('expected_sname', sname)
            expected_srealm = kdc_dict.pop('expected_srealm', srealm)

            expected_salt = client_creds.get_salt()

            authenticator_subkey = self.RandomKey(kcrypto.Enctype.AES256)
            if rep_type == KRB_AS_REP:
                if use_fast:
                    armor_key = self.generate_armor_key(authenticator_subkey,
                                                        armor_tgt.session_key)
                    armor_subkey = authenticator_subkey
                else:
                    armor_key = None
                    armor_subkey = authenticator_subkey
            else:  # KRB_TGS_REP
                if fast_armor_type is not None:
                    armor_subkey = self.RandomKey(kcrypto.Enctype.AES256)
                    explicit_armor_key = self.generate_armor_key(
                        armor_subkey,
                        armor_tgt.session_key)
                    armor_key = kcrypto.cf2(explicit_armor_key.key,
                                            authenticator_subkey.key,
                                            b'explicitarmor',
                                            b'tgsarmor')
                    armor_key = Krb5EncryptionKey(armor_key, None)
                else:
                    armor_key = self.generate_armor_key(authenticator_subkey,
                                                        tgt.session_key)
                    armor_subkey = authenticator_subkey

            if not kdc_dict.pop('include_subkey', True):
                authenticator_subkey = None

            if use_fast:
                generate_fast_fn = kdc_dict.pop('gen_fast_fn', None)
                if generate_fast_fn is None:
                    generate_fast_fn = functools.partial(
                        self.generate_simple_fast,
                        fast_options=fast_options)
            else:
                generate_fast_fn = None

            generate_fast_armor_fn = (
                self.generate_ap_req
                if fast_armor_type is not None
                else None)

            def _generate_padata_copy(_kdc_exchange_dict,
                                      _callback_dict,
                                      req_body,
                                      padata):
                return padata, req_body

            def _check_padata_preauth_key(_kdc_exchange_dict,
                                          _callback_dict,
                                          _rep,
                                          _padata):
                as_rep_usage = KU_AS_REP_ENC_PART
                return preauth_key, as_rep_usage

            pac_options = kdc_dict.pop('pac_options', '1')  # claims support
            pac_options = self.get_pa_pac_options(pac_options)

            kdc_options = kdc_dict.pop('kdc_options', kdc_options_default)

            if rep_type == KRB_AS_REP:
                padata = [pac_request, pac_options]
            else:
                padata = [pac_options]

            gen_padata_fn = kdc_dict.pop('gen_padata_fn', None)
            if gen_padata_fn is not None:
                self.assertEqual(KRB_AS_REP, rep_type)
                self.assertIsNotNone(preauth_etype_info2)

                preauth_key = self.PasswordKey_from_etype_info2(
                    client_creds,
                    preauth_etype_info2[0],
                    client_creds.get_kvno())
                gen_padata = gen_padata_fn(preauth_key, armor_key)
                padata.insert(0, gen_padata)
            else:
                preauth_key = None

            if rep_type == KRB_AS_REP:
                check_padata_fn = _check_padata_preauth_key
            else:
                check_padata_fn = self.check_simple_tgs_padata

            if use_fast:
                inner_padata = padata
                outer_padata = []
            else:
                inner_padata = []
                outer_padata = padata

            if use_fast and fast_cookie is not None:
                outer_padata.append(fast_cookie)

            generate_fast_padata_fn = (functools.partial(_generate_padata_copy,
                                                         padata=inner_padata)
                                       if inner_padata else None)
            generate_padata_fn = (functools.partial(_generate_padata_copy,
                                                    padata=outer_padata)
                                  if outer_padata else None)

            gen_authdata_fn = kdc_dict.pop('gen_authdata_fn', None)
            if gen_authdata_fn is not None:
                auth_data = [gen_authdata_fn()]
            else:
                auth_data = None

            if not use_fast:
                self.assertNotIn('outer_req', kdc_dict)
            outer_req = kdc_dict.pop('outer_req', None)

            if rep_type == KRB_AS_REP:
                kdc_exchange_dict = self.as_exchange_dict(
                    expected_crealm=expected_crealm,
                    expected_cname=expected_cname,
                    expected_cname_private=expected_cname_private,
                    expected_srealm=expected_srealm,
                    expected_sname=expected_sname,
                    ticket_decryption_key=krbtgt_decryption_key,
                    generate_fast_fn=generate_fast_fn,
                    generate_fast_armor_fn=generate_fast_armor_fn,
                    generate_fast_padata_fn=generate_fast_padata_fn,
                    fast_armor_type=fast_armor_type,
                    generate_padata_fn=generate_padata_fn,
                    check_error_fn=check_error_fn,
                    check_rep_fn=check_rep_fn,
                    check_padata_fn=check_padata_fn,
                    check_kdc_private_fn=self.generic_check_kdc_private,
                    callback_dict={},
                    expected_error_mode=expected_error_mode,
                    client_as_etypes=etypes,
                    expected_salt=expected_salt,
                    authenticator_subkey=authenticator_subkey,
                    auth_data=auth_data,
                    armor_key=armor_key,
                    armor_tgt=armor_tgt,
                    armor_subkey=armor_subkey,
                    kdc_options=kdc_options,
                    outer_req=outer_req)
            else:  # KRB_TGS_REP
                kdc_exchange_dict = self.tgs_exchange_dict(
                    expected_crealm=expected_crealm,
                    expected_cname=expected_cname,
                    expected_cname_private=expected_cname_private,
                    expected_srealm=expected_srealm,
                    expected_sname=expected_sname,
                    ticket_decryption_key=target_decryption_key,
                    generate_fast_fn=generate_fast_fn,
                    generate_fast_armor_fn=generate_fast_armor_fn,
                    generate_fast_padata_fn=generate_fast_padata_fn,
                    fast_armor_type=fast_armor_type,
                    generate_padata_fn=generate_padata_fn,
                    check_error_fn=check_error_fn,
                    check_rep_fn=check_rep_fn,
                    check_padata_fn=check_padata_fn,
                    check_kdc_private_fn=self.generic_check_kdc_private,
                    expected_error_mode=expected_error_mode,
                    callback_dict={},
                    tgt=tgt,
                    armor_key=armor_key,
                    armor_tgt=armor_tgt,
                    armor_subkey=armor_subkey,
                    authenticator_subkey=authenticator_subkey,
                    auth_data=auth_data,
                    body_checksum_type=None,
                    kdc_options=kdc_options,
                    outer_req=outer_req)

            repeat = kdc_dict.pop('repeat', 1)
            for _ in range(repeat):
                rep = self._generic_kdc_exchange(kdc_exchange_dict,
                                                 cname=cname,
                                                 realm=crealm,
                                                 sname=sname,
                                                 etypes=etypes)
                if expected_error_mode == 0:
                    self.check_reply(rep, rep_type)

                    fast_cookie = None
                    preauth_etype_info2 = None
                else:
                    self.check_error_rep(rep, expected_error_mode)

                    if 'fast_cookie' in kdc_exchange_dict:
                        fast_cookie = self.create_fast_cookie(
                            kdc_exchange_dict['fast_cookie'])
                    else:
                        fast_cookie = None

                    if expected_error_mode == KDC_ERR_PREAUTH_REQUIRED:
                        preauth_etype_info2 = (
                            kdc_exchange_dict['preauth_etype_info2'])
                    else:
                        preauth_etype_info2 = None

            # Ensure we used all the parameters given to us.
            self.assertEqual({}, kdc_dict)

    def generate_fast_armor_auth_data(self):
        auth_data = self.AuthorizationData_create(AD_FX_FAST_ARMOR, b'')

        return auth_data

    def generate_fast_used_auth_data(self):
        auth_data = self.AuthorizationData_create(AD_FX_FAST_USED, b'')

        return auth_data

    def gen_tgt_fast_armor_auth_data(self):
        user_tgt = self.get_user_tgt()

        ticket_decryption_key = user_tgt.decryption_key

        tgt_encpart = self.getElementValue(user_tgt.ticket, 'enc-part')
        self.assertElementEqual(tgt_encpart, 'etype',
                                ticket_decryption_key.etype)
        self.assertElementKVNO(tgt_encpart, 'kvno',
                               ticket_decryption_key.kvno)
        tgt_cipher = self.getElementValue(tgt_encpart, 'cipher')
        tgt_decpart = ticket_decryption_key.decrypt(KU_TICKET, tgt_cipher)
        tgt_private = self.der_decode(tgt_decpart,
                                      asn1Spec=krb5_asn1.EncTicketPart())

        auth_data = self.generate_fast_armor_auth_data()
        tgt_private['authorization-data'].append(auth_data)

        # Re-encrypt the user TGT.
        tgt_private_new = self.der_encode(
            tgt_private,
            asn1Spec=krb5_asn1.EncTicketPart())
        tgt_encpart = self.EncryptedData_create(ticket_decryption_key,
                                                KU_TICKET,
                                                tgt_private_new)
        user_ticket = user_tgt.ticket.copy()
        user_ticket['enc-part'] = tgt_encpart

        user_tgt = KerberosTicketCreds(
            user_ticket,
            session_key=user_tgt.session_key,
            crealm=user_tgt.crealm,
            cname=user_tgt.cname,
            srealm=user_tgt.srealm,
            sname=user_tgt.sname,
            decryption_key=user_tgt.decryption_key,
            ticket_private=tgt_private,
            encpart_private=user_tgt.encpart_private)

        # Use our modifed TGT to replace the one in the request.
        return user_tgt

    def create_fast_cookie(self, cookie):
        self.assertIsNotNone(cookie)
        if self.strict_checking:
            self.assertNotEqual(0, len(cookie))

        return self.PA_DATA_create(PADATA_FX_COOKIE, cookie)

    def get_pa_pac_request(self, request_pac=True):
        pac_request = self.KERB_PA_PAC_REQUEST_create(request_pac)

        return pac_request

    def get_pa_pac_options(self, options):
        pac_options = self.PA_PAC_OPTIONS_create(options)
        pac_options = self.der_encode(pac_options,
                                      asn1Spec=krb5_asn1.PA_PAC_OPTIONS())
        pac_options = self.PA_DATA_create(PADATA_PAC_OPTIONS, pac_options)

        return pac_options

    def check_kdc_fast_support(self):
        # Check that the KDC supports FAST

        samdb = self.get_samdb()

        krbtgt_rid = 502
        krbtgt_sid = '%s-%d' % (samdb.get_domain_sid(), krbtgt_rid)

        res = samdb.search(base='<SID=%s>' % krbtgt_sid,
                           scope=ldb.SCOPE_BASE,
                           attrs=['msDS-SupportedEncryptionTypes'])

        krbtgt_etypes = int(res[0]['msDS-SupportedEncryptionTypes'][0])

        self.assertTrue(
            security.KERB_ENCTYPE_FAST_SUPPORTED & krbtgt_etypes)
        self.assertTrue(
            security.KERB_ENCTYPE_COMPOUND_IDENTITY_SUPPORTED & krbtgt_etypes)
        self.assertTrue(
            security.KERB_ENCTYPE_CLAIMS_SUPPORTED & krbtgt_etypes)

    def get_service_ticket(self, tgt, target_creds, service='host'):
        etype = (AES256_CTS_HMAC_SHA1_96, ARCFOUR_HMAC_MD5)

        key = tgt.session_key
        ticket = tgt.ticket

        cname = tgt.cname
        realm = tgt.crealm

        target_name = target_creds.get_username()[:-1]
        sname = self.PrincipalName_create(name_type=NT_PRINCIPAL,
                                          names=[service, target_name])

        rep, enc_part = self.tgs_req(cname, sname, realm, ticket, key, etype)

        service_ticket = rep['ticket']

        ticket_etype = service_ticket['enc-part']['etype']
        target_key = self.TicketDecryptionKey_from_creds(target_creds,
                                                         etype=ticket_etype)

        session_key = self.EncryptionKey_import(enc_part['key'])

        service_ticket_creds = KerberosTicketCreds(service_ticket,
                                                   session_key,
                                                   crealm=realm,
                                                   cname=cname,
                                                   srealm=realm,
                                                   sname=sname,
                                                   decryption_key=target_key)

        return service_ticket_creds

    def get_tgt(self, creds):
        user_name = creds.get_username()
        realm = creds.get_realm()

        salt = creds.get_salt()

        etype = (AES256_CTS_HMAC_SHA1_96, ARCFOUR_HMAC_MD5)
        cname = self.PrincipalName_create(name_type=NT_PRINCIPAL,
                                          names=[user_name])
        sname = self.PrincipalName_create(name_type=NT_SRV_INST,
                                          names=['krbtgt', realm])

        till = self.get_KerberosTime(offset=36000)

        krbtgt_creds = self.get_krbtgt_creds()
        ticket_decryption_key = (
            self.TicketDecryptionKey_from_creds(krbtgt_creds))

        kdc_options = str(krb5_asn1.KDCOptions('forwardable,'
                                               'renewable,'
                                               'canonicalize,'
                                               'renewable-ok'))

        pac_request = self.get_pa_pac_request()
        pac_options = self.get_pa_pac_options('1')  # supports claims

        padata = [pac_request, pac_options]

        rep, kdc_exchange_dict = self._test_as_exchange(
            cname=cname,
            realm=realm,
            sname=sname,
            till=till,
            client_as_etypes=etype,
            expected_error_mode=KDC_ERR_PREAUTH_REQUIRED,
            expected_crealm=realm,
            expected_cname=cname,
            expected_srealm=realm,
            expected_sname=sname,
            expected_salt=salt,
            etypes=etype,
            padata=padata,
            kdc_options=kdc_options,
            preauth_key=None,
            ticket_decryption_key=ticket_decryption_key)
        self.check_pre_authentication(rep)

        etype_info2 = kdc_exchange_dict['preauth_etype_info2']

        preauth_key = self.PasswordKey_from_etype_info2(creds,
                                                        etype_info2[0],
                                                        creds.get_kvno())

        ts_enc_padata = self.get_enc_timestamp_pa_data(creds, rep)

        padata = [ts_enc_padata, pac_request, pac_options]

        expected_realm = realm.upper()

        expected_sname = self.PrincipalName_create(
            name_type=NT_SRV_INST, names=['krbtgt', realm.upper()])

        rep, kdc_exchange_dict = self._test_as_exchange(
            cname=cname,
            realm=realm,
            sname=sname,
            till=till,
            client_as_etypes=etype,
            expected_error_mode=0,
            expected_crealm=expected_realm,
            expected_cname=cname,
            expected_srealm=expected_realm,
            expected_sname=expected_sname,
            expected_salt=salt,
            etypes=etype,
            padata=padata,
            kdc_options=kdc_options,
            preauth_key=preauth_key,
            ticket_decryption_key=ticket_decryption_key)
        self.check_as_reply(rep)

        tgt = rep['ticket']

        enc_part = self.get_as_rep_enc_data(preauth_key, rep)
        session_key = self.EncryptionKey_import(enc_part['key'])

        ticket_creds = KerberosTicketCreds(
            tgt,
            session_key,
            crealm=realm,
            cname=cname,
            srealm=realm,
            sname=sname,
            decryption_key=ticket_decryption_key)

        return ticket_creds, enc_part

    def get_mach_tgt(self):
        if self.mach_tgt is None:
            mach_creds = self.get_mach_creds()
            type(self).mach_tgt, type(self).mach_enc_part = (
                self.get_tgt(mach_creds))

        return self.mach_tgt

    def get_user_tgt(self):
        if self.user_tgt is None:
            user_creds = self.get_client_creds()
            type(self).user_tgt, type(self).user_enc_part = (
                self.get_tgt(user_creds))

        return self.user_tgt

    def get_user_service_ticket(self):
        if self.user_service_ticket is None:
            user_tgt = self.get_user_tgt()
            service_creds = self.get_service_creds()
            type(self).user_service_ticket = (
                self.get_service_ticket(user_tgt, service_creds))

        return self.user_service_ticket

    def get_mach_service_ticket(self):
        if self.mach_service_ticket is None:
            mach_tgt = self.get_mach_tgt()
            service_creds = self.get_service_creds()
            type(self).mach_service_ticket = (
                self.get_service_ticket(mach_tgt, service_creds))

        return self.mach_service_ticket


if __name__ == "__main__":
    global_asn1_print = False
    global_hexdump = False
    import unittest
    unittest.main()
