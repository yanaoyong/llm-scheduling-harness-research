#!/usr/bin/env python3
"""Repair over-redacted Python decorators from immutable original snapshots."""
import argparse, ast, json, re
from pathlib import Path
from archive_stage import DEST, save, sha, transform
from supplement_databases import digest, repack

class AbstractText(ast.NodeTransformer):
 def visit_Constant(self,node):
  if isinstance(node.value,str):return ast.copy_location(ast.Constant('__TEXT__'),node)
  if isinstance(node.value,bytes):return ast.copy_location(ast.Constant(b'__BYTES__'),node)
  return node

def main(output):
 release=output/'release';private=output/'private';manifest=json.loads((release/'manifest.json').read_text());indexed={e['path']:e for e in manifest['files']};repairs=json.loads((private/'public-repairs.json').read_text());extras={};checks=[]
 for row in repairs:
  name=row['path'];raw=(private/'snapshot'/name).read_bytes();assert sha(raw)==row['source_sha256']
  current=indexed[name];assert current['sha256']==row['before_sha256']
  public,reason=transform(raw);assert reason is None
  if name.endswith('.py'):
   original_ast=AbstractText().visit(ast.parse(raw));public_ast=AbstractText().visit(ast.parse(public))
   assert ast.dump(original_ast,include_attributes=False)==ast.dump(public_ast,include_attributes=False),name
   assert re.findall(rb'^\s*@([\w.]+)',raw,re.M)==re.findall(rb'^\s*@([\w.]+)',public,re.M),name
   checks.append(name)
  p=private/'public-repairs'/name;p.write_bytes(public);extras[name]=p
  row.update({'sha256':sha(public),'bytes':len(public)})
  current.update({'sha256':sha(public),'bytes':len(public),'transformed':sha(public)!=row['source_sha256']})
 excluded=(DEST/'evidence/excluded.jsonl').read_bytes()
 repack(release/'harness-v6-s1-public.tar.gz',manifest,extras,set(),excluded)
 save(release/'manifest.json',manifest)
 build=json.loads((DEST/'verification/archive-build.json').read_text());build.update({'archive_sha256':digest(release/'harness-v6-s1-public.tar.gz'),'archive_bytes':(release/'harness-v6-s1-public.tar.gz').stat().st_size,'logical_bytes':sum(e['bytes'] for e in manifest['files'])})
 save(release/'archive-build.json',build);save(DEST/'verification/archive-build.json',build)
 save(DEST/'verification/decorator-preservation.json',{'passed':True,'repaired_files':repairs,'python_ast_structure_and_decorators_preserved':checks,'scope':'AST comparison abstracts string/bytes constants only; private path and mailbox substitutions remain allowed. Original source bytes were unchanged.'})
 print(json.dumps({'repaired_files':len(repairs),'python_structures_checked':len(checks),'archive_sha256':build['archive_sha256']}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
