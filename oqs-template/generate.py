#!/usr/bin/env python3

import copy
import glob
import jinja2
import jinja2.ext
import os
import shutil
import subprocess
import yaml

# For files generated, the copyright message can be adapted
# see https://github.com/open-quantum-safe/oqs-provider/issues/2#issuecomment-920904048
# SPDX message to be leading, OpenSSL Copyright notice to be deleted
def fixup_copyright(filename):
   with open(filename, "r") as origfile:
      with open(filename+".new", "w") as newfile:
         newfile.write("// SPDX-License-Identifier: Apache-2.0 AND MIT\n\n")
         skipline = False
         checkline = True
         for line in origfile:
             if checkline==True and " * Copyright" in line:
                skipline=True
             if "*/" in line:
                skipline=False
                checkline=False
             if not skipline:
                newfile.write(line)
   os.rename(filename+".new", filename)

def get_kem_nistlevel(alg):
    if 'LIBOQS_SRC_DIR' not in os.environ:
        print("Must include LIBOQS_SRC_DIR in environment")
        exit(1)
    # translate family names in generate.yml to directory names for liboqs algorithm datasheets
    if alg['family'] == 'CRYSTALS-Kyber': datasheetname = 'kyber'
    elif alg['family'] == 'SIDH': datasheetname = 'sike'
    elif alg['family'] == 'NTRU-Prime': datasheetname = 'ntruprime'
    else: datasheetname = alg['family'].lower()
    # load datasheet
    algymlfilename = os.path.join(os.environ['LIBOQS_SRC_DIR'], 'docs', 'algorithms', 'kem', '{:s}.yml'.format(datasheetname))
    algyml = yaml.safe_load(file_get_contents(algymlfilename, encoding='utf-8'))
    # hacks to match names
    def matches(name, alg):
        def simplify(s):
            return s.lower().replace('_', '').replace('-', '')
        if 'FrodoKEM' in name: name = name.replace('FrodoKEM', 'Frodo')
        if 'Saber-KEM' in name: name = name.replace('-KEM', '')
        if '-90s' in name: name = name.replace('-90s', '').replace('Kyber', 'Kyber90s')
        if simplify(name) == simplify(alg['name_group']): return True
        return False
    # find the variant that matches
    for variant in algyml['parameter-sets']:
        if matches(variant['name'], alg):
            return variant['claimed-nist-level']
    return None

def get_sig_nistlevel(family, alg):
    if 'LIBOQS_SRC_DIR' not in os.environ:
        print("Must include LIBOQS_SRC_DIR in environment")
        exit(1)
    # translate family names in generate.yml to directory names for liboqs algorithm datasheets
    if family['family'] == 'CRYSTALS-Dilithium': datasheetname = 'dilithium'
    elif family['family'] == 'SPHINCS-Haraka': datasheetname = 'sphincs'
    elif family['family'] == 'SPHINCS-SHA2': datasheetname = 'sphincs'
    elif family['family'] == 'SPHINCS-SHAKE': datasheetname = 'sphincs'
    else: datasheetname = family['family'].lower()
    # load datasheet
    algymlfilename = os.path.join(os.environ['LIBOQS_SRC_DIR'], 'docs', 'algorithms', 'sig', '{:s}.yml'.format(datasheetname))
    algyml = yaml.safe_load(file_get_contents(algymlfilename, encoding='utf-8'))
    # hacks to match names
    def matches(name, alg):
        def simplify(s):
            return s.lower().replace('_', '').replace('-', '').replace('+', '')
        if simplify(name) == simplify(alg['name']): return True
        return False
    # find the variant that matches
    for variant in algyml['parameter-sets']:
        if matches(variant['name'], alg):
            return variant['claimed-nist-level']
    return None

def nist_to_bits(nistlevel):
   if nistlevel==1 or nistlevel==2:
      return 128
   elif nistlevel==3 or nistlevel==4:
      return 192
   elif nistlevel==5:
      return 256
   else: 
      return None

def complete_config(config):
   for kem in config['kems']:
      bits_level = nist_to_bits(get_kem_nistlevel(kem))
      if bits_level == None: 
          print("Cannot find security level for {:s} {:s}".format(kem['family'], kem['name_group']))
          exit(1)
      kem['bit_security'] = bits_level

      # now add hybrid_nid to hybrid_groups
      phyb = {}
      if (bits_level == 128):
          phyb['hybrid_group']='p256'
      elif (bits_level == 192):
          phyb['hybrid_group']='p384'
      elif (bits_level == 256):
          phyb['hybrid_group']='p521'
      else:
          print("Warning: Unknown bit level for %s. Cannot assign hybrid." % (kem['group_name']))
          exit(1)
      phyb['bit_security']=bits_level
      phyb['nid']=kem['nid_hybrid']
      kem['hybrids'].insert(0, phyb)

   for famsig in config['sigs']:
      for sig in famsig['variants']:
         bits_level = nist_to_bits(get_sig_nistlevel(famsig, sig))
         if bits_level == None: 
             print("Cannot find security level for {:s} {:s}. Setting to 0.".format(famsig['family'], sig['name']))
             bits_level = 0
         sig['security'] = bits_level
   return config

def run_subprocess(command, outfilename=None, working_dir='.', expected_returncode=0, input=None, ignore_returncode=False):
    result = subprocess.run(
            command,
            input=input,
            stdout=(open(outfilename, "w") if outfilename!=None else subprocess.PIPE),
            stderr=subprocess.PIPE,
            cwd=working_dir,
        )

    if not(ignore_returncode) and (result.returncode != expected_returncode):
        if outfilename == None:
            print(result.stdout.decode('utf-8'))
        assert False, "Got unexpected return code {}".format(result.returncode)

# For list.append in Jinja templates
Jinja2 = jinja2.Environment(loader=jinja2.FileSystemLoader(searchpath="."),extensions=['jinja2.ext.do'])

def file_get_contents(filename, encoding=None):
    with open(filename, mode='r', encoding=encoding) as fh:
        return fh.read()

def file_put_contents(filename, s, encoding=None):
    with open(filename, mode='w', encoding=encoding) as fh:
        fh.write(s)

def populate(filename, config, delimiter, overwrite=False):
    fragments = glob.glob(os.path.join('oqs-template', filename, '*.fragment'))
    if overwrite == True:
        source_file = os.path.join('oqs-template', filename, os.path.basename(filename)+ '.base')
        contents = file_get_contents(source_file)
    else:
        contents = file_get_contents(filename)
    for fragment in fragments:
        identifier = os.path.splitext(os.path.basename(fragment))[0]
        if filename.endswith('.md'):
            identifier_start = '{} OQS_TEMPLATE_FRAGMENT_{}_START -->'.format(delimiter, identifier.upper())
        else:
            identifier_start = '{} OQS_TEMPLATE_FRAGMENT_{}_START'.format(delimiter, identifier.upper())
        identifier_end = '{} OQS_TEMPLATE_FRAGMENT_{}_END'.format(delimiter, identifier.upper())
        preamble = contents[:contents.find(identifier_start)]
        postamble = contents[contents.find(identifier_end):]
        if overwrite == True:
            contents = preamble + Jinja2.get_template(fragment).render({'config': config}) + postamble.replace(identifier_end + '\n', '')
        else:
            contents = preamble + identifier_start + Jinja2.get_template(fragment).render({'config': config}) + postamble
    file_put_contents(filename, contents)

def load_config(include_disabled_sigs=False):
    config = file_get_contents(os.path.join('oqs-template', 'generate.yml'), encoding='utf-8')
    config = yaml.safe_load(config)
    if not include_disabled_sigs:
        for sig in config['sigs']:
            sig['variants'] = [variant for variant in sig['variants'] if ('enable' in variant and variant['enable'])]

    # remove KEMs without NID (old stuff)
    newkems = []
    for kem in config['kems']:
        if 'nid' in kem:
           newkems.append(kem)
    config['kems']=newkems

    # remove SIGs without OID (old stuff)
    for sig in config['sigs']:
        newvars = []
        for variant in sig['variants']:
            if 'oid' in variant:
                newvars.append(variant)
        sig['variants']=newvars

    for kem in config['kems']:
        kem['hybrids'] = []
        try:
            for extra_nid_current in kem['extra_nids']['current']:
                extra_hybrid = extra_nid_current
                if extra_nid_current['hybrid_group'] == "x25519" or extra_nid_current['hybrid_group'] == "p256":
                   extra_hybrid['bit_security']=128
                if extra_nid_current['hybrid_group'] == "x448" or extra_nid_current['hybrid_group'] == "p384":
                   extra_hybrid['bit_security']=192
                if extra_nid_current['hybrid_group'] == "p521":
                   extra_hybrid['bit_security']=256
                kem['hybrids'].append(extra_hybrid)
                if 'hybrid_group' in extra_nid_current and extra_nid_current['hybrid_group'] in ["x25519", "x448"]:
                    extra_hyb_nid = extra_nid_current['nid']
                    if 'nid_ecx_hybrid' in kem:
                        print("Warning, duplicate nid_ecx_hybrid for",
                              kem['name_group'], ":", extra_hyb_nid, "in generate.yml,",
                              kem['nid_ecx_hybrid'], "in generate_extras.yml, using generate.yml entry.")
                    kem['nid_ecx_hybrid'] = extra_hyb_nid
        except KeyError as ke:
            pass
    return config

# extend config with "hybrid_groups" array:
config = load_config() # extend config with "hybrid_groups" array

# complete config with "bit_security" and "hybrid_group from 
# nid_hybrid information
config = complete_config(config)


populate('oqsprov/oqsencoders.inc', config, '/////')
populate('oqsprov/oqsdecoders.inc', config, '/////')
populate('oqsprov/oqs_prov.h', config, '/////')
populate('oqsprov/oqsprov.c', config, '/////')
populate('oqsprov/oqsprov_capabilities.c', config, '/////')
populate('oqsprov/oqs_kmgmt.c', config, '/////')
populate('oqsprov/oqs_encode_key2any.c', config, '/////')
populate('oqsprov/oqs_decode_der2key.c', config, '/////')
populate('oqsprov/oqsprov_keys.c', config, '/////')

config2 = load_config(include_disabled_sigs=True)
config2 = complete_config(config2)

populate('ALGORITHMS.md', config2, '<!---')
populate('README.md', config2, '<!---')
print("All files generated")
os.environ["LIBOQS_DOCS_DIR"]=os.path.join(os.environ["LIBOQS_SRC_DIR"], "docs")
import generate_oid_nid_table
