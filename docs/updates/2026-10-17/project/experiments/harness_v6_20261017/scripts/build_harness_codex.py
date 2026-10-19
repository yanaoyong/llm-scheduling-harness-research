"""Build the dedicated tool-restricted Codex from an exact upstream checkout.

Dependencies may be downloaded by Cargo; this script never starts a model run.
The user installation and configuration are never modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
# Archived fork builder; not a production dependency.
SOURCE_COMMIT = '83086188ae0614bd882818ff1aa23f3194962012'
ISOLATED_VERSION = 'codex-cli 0.163.0-harness-v6.5'
from harness_v6.work_paths import checked_output


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(source, output, *, work_root, cargo_home, rustup_home, v8_artifact_dir,
          target_dir=None, offline=False):
    source = Path(source).resolve()
    output = checked_output(output, work_root, inputs=[source])
    patch = Path(__file__).resolve().parents[1]/'patches/codex-0.163.0-harness-v6.5.patch'
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args])
    if git('rev-parse', 'HEAD').decode().strip() != SOURCE_COMMIT:
        raise ValueError('upstream source commit mismatch')
    # Use the exact sandbox archive/binding pair published and pinned by Codex.
    # Upstream rusty_v8 does not publish this sandbox variant for Darwin.
    trusted = dict((name, digest) for digest, name in (
        line.split() for line in (source/'third_party/v8/rusty_v8_150_4_0.sha256').read_text().splitlines()))
    artifacts = Path(v8_artifact_dir).resolve()
    archive = list(artifacts.glob('librusty_v8_ptrcomp_sandbox_release_*.a.gz'))
    binding = list(artifacts.glob('src_binding_ptrcomp_sandbox_release_*.rs'))
    if len(archive) != 1 or len(binding) != 1:
        raise ValueError('provide one matching Codex V8 archive/binding pair')
    archive, binding = archive[0], binding[0]
    if archive.name.removeprefix('librusty_v8_').removesuffix('.a.gz') != binding.name.removeprefix('src_binding_').removesuffix('.rs'):
        raise ValueError('V8 archive/binding target mismatch')
    for artifact in (archive, binding):
        if sha(artifact) != trusted.get(artifact.name):
            raise ValueError('V8 artifact does not match pinned upstream checksum')
    # Reject unrelated modifications and reuse only this exact applied patch.
    diff = git('diff', '--binary')
    if diff:
        if diff != patch.read_bytes():
            raise ValueError('source has changes other than the pinned isolation patch')
    else:
        subprocess.run(['git','-C',str(source),'apply','--check',str(patch)],check=True)
        subprocess.run(['git','-C',str(source),'apply',str(patch)],check=True)
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, CARGO_HOME=str(Path(cargo_home).resolve()),
        RUSTUP_HOME=str(Path(rustup_home).resolve()), CARGO_INCREMENTAL='0',
        CARGO_BUILD_JOBS='4', CARGO_NET_GIT_FETCH_WITH_CLI='true',
        CARGO_HTTP_MULTIPLEXING='false')
    env['PATH'] = str(Path(cargo_home).resolve()/'bin')+os.pathsep+env.get('PATH','')
    target = checked_output(target_dir or source/'codex-rs/target', work_root)
    env.update(CARGO_TARGET_DIR=str(target), RUSTY_V8_ARCHIVE=str(archive),
               RUSTY_V8_SRC_BINDING_PATH=str(binding))
    argv = [str(Path(cargo_home).resolve()/'bin/cargo'), '+1.95.0', 'build', '--locked',
            '--profile', 'dev-small', '-p', 'codex-cli', '--bin', 'codex']
    if offline: argv.append('--offline')
    with (output/'build.log').open('xb') as log:
        subprocess.run(argv, cwd=source/'codex-rs', env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    if git('diff', '--binary') != patch.read_bytes():
        raise ValueError('source changed during the build')
    binary = output/'codex-harness-v6'
    shutil.copy2(target/'dev-small/codex', binary)
    for name, child in (('HOME','version-home'),('CODEX_HOME','version-codex-home')):
        path=output/child;path.mkdir()
        env[name]=str(path)
    version = subprocess.check_output([str(binary),'--version'],env=env).decode().strip()
    if version != ISOLATED_VERSION:
        raise ValueError('built binary version mismatch')
    manifest = dict(source_commit=SOURCE_COMMIT, source_tag='rust-v0.163.0',
        patch_sha256=sha(patch), lock_sha256=sha(source/'codex-rs/Cargo.lock'),
        binary_sha256=sha(binary), binary=str(binary),
        version=version, rust_toolchain='1.95.0', command=argv,
        target_dir=str(target), v8_artifacts=[dict(path=str(p),sha256=sha(p)) for p in (archive,binding)],
        real_model_requests=0, purpose='Harness-only local build, not an upstream release')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','work-root','cargo-home','rustup-home','v8-artifact-dir'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--target-dir')
    p.add_argument('--offline',action='store_true')
    a=p.parse_args()
    print(json.dumps(build(a.source,a.output,work_root=a.work_root,cargo_home=a.cargo_home,rustup_home=a.rustup_home,
        v8_artifact_dir=a.v8_artifact_dir,target_dir=a.target_dir,offline=a.offline)))
