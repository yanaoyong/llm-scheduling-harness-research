"""Standalone saved-trace audit bundle; no runner or model integration.

Each complete component report remains a separate, hash-bound file. The final
small manifest is published last. This API never reconstructs a full event list
or reads the complete source/opportunity report back into memory. Metrics and
physical output arrays still grow in memory; long-window readiness is not claimed.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from types import ModuleType

from src.smt_fullfab import stream_source_audit, stream_opportunity_audit
from src.smt_fullfab import stream_physical_projection, stream_metrics
from src.smt_fullfab.trace_source import inspect_jsonl, scan_envelope, SourceChangedError

ROOT = Path(__file__).resolve().parents[2]
BINDING_PATH = 'src/smt_fullfab/stream_physical_binding.py'
DEPENDENCIES = {
    BINDING_PATH: 'db8ce98dccd7b004b9da595eab93d5eeac1b308ca50af62f961e9f23865877a2',
    'src/smt_fullfab/stream_metrics.py': '00c6ccb42581f2412d12f10934f940403bdcd4745e438a7acc60173cb1cc2d35',
    'src/smt_fullfab/metrics.py': 'c954c83a51d3ebff7614b469086c916357ef7424d8f92bae25c9c0e533a962cc',
    'src/smt_fullfab/stream_source_audit.py': '1d2b55073b17d851239d0df0317447bed1b2e45176e882e514fee75b7f0f7463',
    'src/smt_fullfab/stream_opportunity_audit.py': 'f17b2648720f5a971849df1326a02fa457aca755f8ac8bfe6691f08d7ce45bcd',
}
SCHEMA = 'smt-saved-trace-audit-bundle-v1'
MANIFEST = 'audit_bundle.json'
MEMBERS = frozenset(('source.json', 'opportunity.json', 'physical.json', 'metrics.json',
                     'projection/projection.json', 'projection/physical.jsonl'))


def sha_file(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def dependencies():
    for path,expected in DEPENDENCIES.items():
        if sha_file(ROOT/path)!=expected:raise ValueError('audit dependency changed: '+path)


raw=(ROOT/BINDING_PATH).read_bytes()
if hashlib.sha256(raw).hexdigest()!=DEPENDENCIES[BINDING_PATH]:raise ValueError('binding source changed')
binding=ModuleType('isolated_physical_binding_for_bundle')
binding.__file__=str(ROOT/BINDING_PATH)
exec(compile(raw,binding.__file__,'exec'),binding.__dict__)
DEPENDENCIES.update(binding.DEPENDENCIES)


def _receipt_equal(actual,expected):
    # Preserve numeric types, not Python's bool/int or int/float aliases.
    return binding._canonical(actual)==binding._canonical(expected)


def audit_to_bundle(source, *, output_dir, expected_source_sha256,
                    verify_data_dir=None, window_start=0, priority_weights=None,
                    require_terminal=True, work_dir=None):
    """Create a new bundle from externally identified source bytes.

    Any interrupted or failed component leaves diagnostic files but no complete
    bundle manifest. Fully consumed semantic failures can produce valid=False.
    A valid prefix, if explicitly requested, is never a completed-window result.
    This certifies saved trace physics/provenance/opportunities only; it does not
    certify model authorship, run resources, checkpoint state or official parity.
    """
    if expected_source_sha256 is None:raise ValueError('an external source SHA is required')
    if type(require_terminal) is not bool:raise TypeError('require_terminal must be boolean')
    dependencies()
    output=Path(output_dir).absolute()
    output=output.parent.resolve(strict=True)/output.name
    output.mkdir()  # create-new; never reuse a partial or completed bundle
    seal=inspect_jsonl(source,expected_sha256=expected_source_sha256)
    envelope=scan_envelope(seal,require_terminal=require_terminal)
    receipt=asdict(envelope.receipt)
    identities={seal.path:seal.file_identity}

    def fence(): binding._fence(identities)

    def member(name,expected_sha):
        path=output/name
        before=binding._regular_identity(path)
        if sha_file(path)!=expected_sha:raise SourceChangedError('audit member hash changed: '+name)
        binding._fence({path:before})
        identities[path]=before
        return {'sha256':expected_sha,'bytes':before[2]}

    provenance=stream_source_audit.audit_plan_sources(seal,report_path=output/'source.json',work_dir=work_dir)
    opportunities=stream_opportunity_audit.audit_opportunity_coverage(seal,report_path=output/'opportunity.json',work_dir=work_dir)
    for description in (provenance,opportunities):
        if not description['complete_jsonl_pass'] or not _receipt_equal(description['source_receipt'],receipt):
            raise SourceChangedError('audit component source receipt mismatch')
    created=stream_physical_projection.project_physical_trace(seal,output_dir=output/'projection')
    if not _receipt_equal(created['source_receipt'],receipt):raise SourceChangedError('projection source mismatch')
    physical=binding.audit_projection_to_file(output/'projection',source=seal,
        expected_evidence={k:created[k] for k in ('manifest_sha256','source_receipt','output_receipt')},
        report_path=output/'physical.json',verify_data_dir=verify_data_dir,work_dir=work_dir)
    metrics=stream_metrics.compute_metrics(seal.path,window_start=window_start,
        priority_weights=priority_weights,expected_source_sha256=seal.sha256)
    metric_report={'schema':'smt-source-bound-metrics-v1','metrics':metrics,
        '_source_evidence':{'source_receipt':receipt,'binding':'both full raw-byte passes match source SHA',
                            'implementation_sha256':DEPENDENCIES['src/smt_fullfab/stream_metrics.py']}}
    metric_descriptor=binding._publish_report(metric_report,output/'metrics.json',fence)
    members={name:member(name,expected) for name,expected in (
        ('source.json',provenance['report_sha256']),('opportunity.json',opportunities['report_sha256']),
        ('physical.json',physical['report_sha256']),('metrics.json',metric_descriptor['report_sha256']),
        ('projection/projection.json',created['manifest_sha256']),
        ('projection/physical.jsonl',created['output_receipt']['sha256']))}
    valid=bool(provenance['valid'] and opportunities['valid'] and physical['physical_valid'])
    summary={'valid':valid,'source_valid':provenance['valid'],'opportunity_valid':opportunities['valid'],
        'physical_valid':physical['physical_valid'],
        'actual_dispatch_provenance_complete':provenance['actual_dispatch_provenance_complete'],
        'absence_of_unreported_legal_demand_certified':bool(valid and opportunities['unreported_uncovered_legal_demand_absent']),
        'complete_physical_window_certified':bool(valid and envelope.terminal_at_eof),
        'verified_input_hashes':bool(verify_data_dir) and bool(physical['physical_valid']),
        'source_errors':provenance['errors'],'opportunity_errors':opportunities['errors'],
        'physical_error_details_member':'physical.json',
        'metrics':{key:metrics[key] for key in ('window_start','window_end','weighted_tardy_lot_hours',
            'throughput_lots','terminal_wip_lots','terminal_tardy_wip_lots')}}
    report={'schema':SCHEMA,'status':'complete','summary':summary,'members':members,
        'source_receipt':receipt,'envelope':asdict(envelope),
        'configuration':{'window_start':window_start,'priority_weights':priority_weights,
                         'require_terminal':require_terminal,'verify_data_dir_supplied':verify_data_dir is not None},
        'dependency_sha256':dict(DEPENDENCIES),
        'bundle_source_sha256':sha_file(__file__),
        'scope':{'model_attribution_certified':False,'run_resource_acceptance_certified':False,
            'snapshot_restoration_certified':False,'official_simulator_equivalence_certified':False,
            'long_window_readiness_certified':False,'physical_and_metric_output_arrays_still_in_memory':True,
            'standalone_saved_trace_only':True,'source_hash_external_trust':'caller supplied'}}
    fence();dependencies()
    published=binding._publish_report(report,output/MANIFEST,fence)
    return {**published,'bundle_path':str(output),'summary':summary,'source_receipt':receipt}


def read_bundle(output_dir, *, expected_manifest_sha256):
    """Recheck all actual member bytes against an externally identified manifest.

    This is storage verification, not a second semantic replay. Receipts bind
    bytes read at this time; returned paths are not a perpetual authorization.
    """
    if not binding._sha(expected_manifest_sha256):raise ValueError('external manifest SHA required')
    directory=Path(output_dir)
    if directory.is_symlink():raise ValueError('bundle directory cannot be a symlink')
    directory=directory.resolve(strict=True)
    path=directory/MANIFEST;identity=binding._regular_identity(path)
    if identity[2]>1024*1024:raise ValueError('bundle manifest too large')
    with path.open('rb') as stream:
        if binding._identity(os.fstat(stream.fileno()))!=identity:raise SourceChangedError('manifest replaced')
        raw=stream.read(1024*1024+1)
        if binding._identity(os.fstat(stream.fileno()))!=identity:raise SourceChangedError('manifest changed')
    if hashlib.sha256(raw).hexdigest()!=expected_manifest_sha256:raise SourceChangedError('manifest SHA mismatch')
    report=json.loads(raw)
    if report.get('schema')!=SCHEMA or report.get('status')!='complete' or set(report['members'])!=MEMBERS:
        raise ValueError('incomplete bundle structure')
    identities={path:identity}
    for name,metadata in report['members'].items():
        member=directory/name
        if member.parent!=directory and member.parent.is_symlink():raise ValueError('member parent is a symlink')
        before=binding._regular_identity(member)
        if before[2]!=metadata['bytes'] or sha_file(member)!=metadata['sha256']:
            raise SourceChangedError('audit member differs: '+name)
        identities[member]=before;binding._fence({member:before})
    binding._fence(identities)
    return {'storage_verified':True,'summary':report['summary'],'source_receipt':report['source_receipt'],
            'manifest_sha256':expected_manifest_sha256,'semantic_replay_performed':False}
