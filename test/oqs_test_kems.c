// SPDX-License-Identifier: Apache-2.0 AND MIT

#include <openssl/evp.h>
#include <openssl/provider.h>
#include "test_common.h"
#include <string.h>
#include "oqs/oqs.h"

static OSSL_LIB_CTX *libctx = NULL;
static char *modulename = NULL;
static char *configfile = NULL;

static int test_oqs_kems(const char *kemalg_name)
{
  EVP_MD_CTX *mdctx = NULL;
  EVP_PKEY_CTX *ctx = NULL;
  EVP_PKEY *key = NULL;
  unsigned char *out, *secenc, *secdec;
  size_t outlen, seclen;

  int testresult = 1;

  if (!alg_is_enabled(kemalg_name)) {
     printf("Not testing disabled algorithm %s.\n", kemalg_name);
     return 1;
  }
  // test with built-in digest only if default provider is active:
  // TBD revisit when hybrids are activated: They always need default provider
  if (OSSL_PROVIDER_available(libctx, "default")) {
    testresult &=
      (ctx = EVP_PKEY_CTX_new_from_name(libctx, kemalg_name, NULL)) != NULL
      && EVP_PKEY_keygen_init(ctx)
      && EVP_PKEY_generate(ctx, &key);

    if (!testresult) goto err;
    OPENSSL_free(ctx);
    ctx = NULL;

    testresult &=
      (ctx = EVP_PKEY_CTX_new_from_pkey(libctx, key, NULL)) != NULL
      && EVP_PKEY_encapsulate_init(ctx, NULL)
      && EVP_PKEY_encapsulate(ctx, NULL, &outlen, NULL, &seclen)
      && (out = OPENSSL_malloc(outlen)) != NULL
      && (secenc = OPENSSL_malloc(seclen)) != NULL
      && memset(secenc, 0x11, seclen) != NULL
      && (secdec = OPENSSL_malloc(seclen)) != NULL
      && memset(secdec, 0xff, seclen) != NULL
      && EVP_PKEY_encapsulate(ctx, out, &outlen, secenc, &seclen)
      && EVP_PKEY_decapsulate_init(ctx, NULL)
      && EVP_PKEY_decapsulate(ctx, secdec, &seclen, out, outlen)
      && memcmp(secenc, secdec, seclen) == 0;
    if (!testresult) goto err;

    out[0] = ~out[0];
    out[outlen - 1] = ~out[outlen - 1];
    testresult &=
      memset(secdec, 0xff, seclen) != NULL
      && EVP_PKEY_decapsulate_init(ctx, NULL)
      && (EVP_PKEY_decapsulate(ctx, secdec, &seclen, out, outlen) || 1)
      && memcmp(secenc, secdec, seclen) != 0;
  }

err:
  EVP_PKEY_free(key);
  OPENSSL_free(ctx);
  return testresult;
}

#define nelem(a) (sizeof(a)/sizeof((a)[0]))

int main(int argc, char *argv[])
{
  size_t i;
  int errcnt = 0, test = 0, query_nocache;
  OSSL_PROVIDER *oqsprov = NULL;
  const OSSL_ALGORITHM *kemalgs;

  T((libctx = OSSL_LIB_CTX_new()) != NULL);
  T(argc == 3);
  modulename = argv[1];
  configfile = argv[2];

  T(OSSL_LIB_CTX_load_config(libctx, configfile));

  T(OSSL_PROVIDER_available(libctx, modulename));
  oqsprov = OSSL_PROVIDER_load(libctx, modulename);

  kemalgs = OSSL_PROVIDER_query_operation(oqsprov, OSSL_OP_KEM, &query_nocache);
  if (kemalgs) {
      for (; kemalgs->algorithm_names != NULL; kemalgs++) {
            if (test_oqs_kems(kemalgs->algorithm_names)) {
              fprintf(stderr,
                 cGREEN "  KEM test succeeded: %s" cNORM "\n",
                 kemalgs->algorithm_names);
            } else {
              fprintf(stderr,
                 cRED "  KEM test failed: %s" cNORM "\n",
                 kemalgs->algorithm_names);
              ERR_print_errors_fp(stderr);
              errcnt++;
            }
      }
  }

  OSSL_LIB_CTX_free(libctx);

  TEST_ASSERT(errcnt == 0)
  return !test;
}
