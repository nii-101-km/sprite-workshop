"""Sprite generation and image processing for the workshop.
The caller coordinates GPU usage; ComfyUI cleanup is checked after generation.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import re
import fcntl
import tempfile
import urllib.parse
from contextlib import contextmanager as _contextmanager
from pathlib import Path as _Path
from typing import Any, Dict, List, Optional
import sprite_tools as _package

_processing = _package.processing
_adapter_registry = _package.adapters
_BackendFailure = _package.comfy_client._BackendFailure
_WORK_ROOT = None
_RESULTS_DIR = None
_JOBS_DIR = None

def configure(work_root):
    """Set the isolated worker's storage directory before handling a request."""
    global _WORK_ROOT, _RESULTS_DIR, _JOBS_DIR
    _WORK_ROOT = str(_Path(work_root).expanduser().resolve())
    _RESULTS_DIR = os.path.join(_WORK_ROOT, 'results')
    _JOBS_DIR = os.path.join(_RESULTS_DIR, 'jobs')

COMFYUI_BASE_URL: str = "http://127.0.0.1:8188"
COMFYUI_CONNECT_TIMEOUT: int = 5
COMFYUI_READ_TIMEOUT: int = 30
COMFYUI_POLL_INTERVAL: float = 2.0
COMFYUI_GENERATION_TIMEOUT: int = 600
MAX_ATTEMPTS: int = 3

GRID_MIN: int = 8
GRID_MAX: int = 256
PALETTE_MIN: int = 2
PALETTE_MAX: int = 256
EXPORT_SCALE_MIN: int = 1
EXPORT_SCALE_MAX: int = 16
GRID_PRESETS: List[int] = [16, 32, 64, 128]
SUPPORTED_MODELS: List[str] = list(_adapter_registry.models())


def _safe_path(relative_path: str) -> str:
    if not relative_path or not isinstance(relative_path, str):
        raise ValueError("Path must be a non-empty string")
    if os.path.isabs(relative_path):
        raise ValueError(f"Absolute paths are not allowed: {relative_path!r}")
    if ".." in relative_path.split(os.sep):
        raise ValueError(f"Path traversal (..) is not allowed: {relative_path!r}")
    resolved = os.path.realpath(os.path.join(_WORK_ROOT, relative_path))
    if not resolved.startswith(_WORK_ROOT + os.sep) and resolved != _WORK_ROOT:
        raise ValueError(f"Path escapes working root: {relative_path!r}")
    return resolved


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _validate_grid(grid_width: int, grid_height: int) -> None:
    if not isinstance(grid_width, int) or isinstance(grid_width, bool):
        raise ValueError("grid_width must be an integer")
    if not isinstance(grid_height, int) or isinstance(grid_height, bool):
        raise ValueError("grid_height must be an integer")
    if not (GRID_MIN <= grid_width <= GRID_MAX):
        raise ValueError(f"grid_width must be {GRID_MIN}..{GRID_MAX}, got {grid_width}")
    if not (GRID_MIN <= grid_height <= GRID_MAX):
        raise ValueError(f"grid_height must be {GRID_MIN}..{GRID_MAX}, got {grid_height}")


def _validate_palette(palette_colors: int) -> None:
    if not isinstance(palette_colors, int) or isinstance(palette_colors, bool):
        raise ValueError("palette_colors must be an integer")
    if not (PALETTE_MIN <= palette_colors <= PALETTE_MAX):
        raise ValueError(f"palette_colors must be {PALETTE_MIN}..{PALETTE_MAX}, got {palette_colors}")


def _validate_export_scale(export_scale: int) -> None:
    if not isinstance(export_scale, int) or isinstance(export_scale, bool):
        raise ValueError("export_scale must be an integer")
    if not (EXPORT_SCALE_MIN <= export_scale <= EXPORT_SCALE_MAX):
        raise ValueError(f"export_scale must be {EXPORT_SCALE_MIN}..{EXPORT_SCALE_MAX}, got {export_scale}")


def _parse_hex_color(color_str: str) -> tuple:
    s = color_str.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) != 6:
        raise ValueError(f"Invalid hex color: {color_str!r}, expected #RRGGBB")
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        raise ValueError(f"Invalid hex color: {color_str!r}")
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        raise ValueError(f"Color channel out of range: {color_str!r}")
    return (r, g, b)


# --- ComfyUI client helpers ---


# --- API graph builders ---


# --- Job persistence helpers ---


# ---------------------------------------------------------------------------
# Public functions (exported to Worker)
# ---------------------------------------------------------------------------


def sprite_pixelize(
    input_path: str,
    grid_width: int = 32,
    grid_height: int = 32,
    palette_colors: int = 16,
    export_scale: int = 4,
    remove_background: bool = False,
    background_color: Optional[str] = None,
) -> dict:
    """Deterministically pixelize an existing image to a sprite grid.

    Each call produces a unique operation_id and separate output directory,
    so repeated calls with identical parameters never overwrite prior results.

    Args:
        input_path: Relative path to input PNG (must be within working root).
        grid_width: Output grid width in pixels (8..256).
        grid_height: Output grid height in pixels (8..256).
        palette_colors: Maximum number of colors for opaque pixels (2..256).
        export_scale: Nearest-neighbor upscale factor for export (1..16).
        remove_background: If true, remove pixels matching background_color.
        background_color: Hex color #RRGGBB to remove (required if remove_background).

    Returns:
        dict with sprite_path, export_path, dimensions, SHA256, palette, alpha info,
        operation_id, metadata_path, and input_sha256.
    """
    _validate_grid(grid_width, grid_height)
    _validate_palette(palette_colors)
    _validate_export_scale(export_scale)

    resolved = _safe_path(input_path)
    if not os.path.isfile(resolved):
        raise ValueError(f"Input file not found: {input_path!r}")

    if remove_background and background_color is None:
        raise ValueError("background_color is required when remove_background is true")

    input_sha = _sha256_file(resolved)
    operation_id = uuid.uuid4().hex[:12]
    param_key = f"{grid_width}x{grid_height}_p{palette_colors}_x{export_scale}"
    dir_name = f"{os.path.basename(input_path)[:-4]}_{input_sha[:12]}_{param_key}_{operation_id}"
    result_dir = os.path.join(_RESULTS_DIR, "pixelize", dir_name)
    _ensure_dir(result_dir)

    result = _pixelize_image(
        input_path=resolved,
        grid_width=grid_width,
        grid_height=grid_height,
        palette_colors=palette_colors,
        export_scale=export_scale,
        remove_background=remove_background,
        background_color=background_color,
        result_dir=result_dir,
    )

    metadata = {
        "operation_id": operation_id,
        "input_path": input_path,
        "input_sha256": input_sha,
        "grid_width": grid_width,
        "grid_height": grid_height,
        "palette_colors": palette_colors,
        "export_scale": export_scale,
        "remove_background": remove_background,
        "background_color": background_color,
        "sprite_path": result["sprite_path"],
        "sprite_sha256": result["sprite_sha256"],
        "export_path": result["export_path"],
        "export_sha256": result["export_sha256"],
        "provenance": "sprite_pixelize",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    metadata_path = os.path.join(result_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    result["operation_id"] = operation_id
    result["metadata_path"] = os.path.relpath(metadata_path, _WORK_ROOT)
    result["input_sha256"] = input_sha
    return result


# Persistence and the Qwen adapter lifecycle. No automatic retries or model ownership.


def _validate_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'(?:[a-f0-9]{12}|[a-f0-9]{32})', value):
        raise ValueError('Expected a hexadecimal job ID')
    return value


def _write_json(path: str, value: dict) -> None:
    directory = os.path.dirname(path)
    _ensure_dir(directory)
    fd, temporary = tempfile.mkstemp(prefix='.record-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _ensure_dir(path: str) -> None:
    resolved = os.path.realpath(path)
    if os.path.commonpath([resolved, _WORK_ROOT]) != _WORK_ROOT:
        raise ValueError('Output directory escapes workdir')
    os.makedirs(path, exist_ok=True)


def _save_job(job_id: str, data: dict) -> None:
    _validate_id(job_id)
    _write_json(_safe_path(f'results/jobs/{job_id}.json'), data)


def _load_job(job_id: str) -> Optional[dict]:
    _validate_id(job_id)
    path = _safe_path(f'results/jobs/{job_id}.json')
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


@_contextmanager
def _generation_lock():
    _ensure_dir(_WORK_ROOT)
    path = _safe_path('.sprite-generation.lock')
    with open(path, 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another sprite generation owns this workdir') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _inspect_image(input_path: str) -> dict:
    """Internal CPU image measurements; not exported as an agent function."""
    path = _safe_path(input_path)
    return {'input_path': input_path, 'sha256': _sha256_file(path), **_image_facts(path)}


def sprite_capabilities() -> dict:
    """List registered adapters and CPU tools; does not contact model servers."""
    return {'models': SUPPORTED_MODELS, 'operations':['generate','edit','pixelize'],
            'backend':'comfyui', 'adapters':{name:_adapter_registry.get_adapter(name).capabilities() for name in SUPPORTED_MODELS},
            'grid_presets': GRID_PRESETS,'grid_limits':{'min':GRID_MIN,'max':GRID_MAX},
            'palette_limits':{'min':PALETTE_MIN,'max':PALETTE_MAX},
            'export_scale_limits':{'min':EXPORT_SCALE_MIN,'max':EXPORT_SCALE_MAX},
            'max_attempts_per_lineage':MAX_ATTEMPTS,
            'gpu_execution':'synchronous; caller owns exclusive GPU/release lifecycle',
            'unsupported':['animation','sprite_sheets','sketch','inpaint']}


def _reserve_attempt(kind: str, model: str, reference_sha: Optional[str], retry_of: Optional[str]) -> dict:
    job_id = uuid.uuid4().hex
    parent = None
    if retry_of is not None:
        parent = _load_job(retry_of)
        if parent is None:
            raise ValueError('retry_of_job_id does not exist')
        if parent['type'] != kind or parent['model'] != model or parent.get('reference_sha256') != reference_sha:
            raise ValueError('Retry must keep operation, model and reference; start a new lineage otherwise')
        lineage_id = parent['lineage_id']
        ledger_path = _safe_path(f'results/lineages/{lineage_id}.json')
        with open(ledger_path, encoding='utf-8') as handle:
            ledger = json.load(handle)
        if ledger['jobs'][-1] != retry_of:
            raise ValueError('Retry the latest job only; branching retries are not supported')
        if parent['status'] in ['pending', 'submitting', 'running', 'unknown']:
            raise ValueError('Previous backend state is unresolved; retry is forbidden')
        if len(ledger['jobs']) >= MAX_ATTEMPTS:
            raise ValueError('Attempt limit reached for this lineage')
    else:
        lineage_id = uuid.uuid4().hex
        ledger_path = _safe_path(f'results/lineages/{lineage_id}.json')
        ledger = {'lineage_id': lineage_id, 'max_attempts': MAX_ATTEMPTS, 'jobs': []}
    ledger['jobs'].append(job_id)
    record = {'job_id': job_id, 'lineage_id': lineage_id, 'attempt_id': uuid.uuid4().hex,
              'attempt_index': len(ledger['jobs']), 'retry_of_job_id': retry_of,
              'type': kind, 'model': model, 'reference_sha256': reference_sha,
              'status': 'pending', 'errors': [], 'revisions': [],
              'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'acceptance': {'status': 'not_reviewed', 'view': 'not_reviewed'}}
    if os.environ.get('SPRITE_WORKSHOP_JOB_ID'):
        record['workshop_job_id'] = os.environ['SPRITE_WORKSHOP_JOB_ID']
    _save_job(job_id, record)
    # Saving the ledger after the reserved job makes a crash conservative: a pending
    # attempt cannot be retried silently, and no accepted ID is reused.
    _write_json(ledger_path, ledger)
    return record


def _run_generation(kind: str, prompt: str, model: str, seed: int, postprocess: bool,
                    grid_width: int, grid_height: int, palette_colors: int, export_scale: int,
                    remove_background: bool, background_color: Optional[str],
                    reference_path: Optional[str], retry_of_job_id: Optional[str]) -> dict:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('prompt must be a non-empty string')
    adapter = _adapter_registry.get_adapter(model)
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('seed must be an unsigned 64-bit integer')
    if type(postprocess) is not bool or type(remove_background) is not bool:
        raise ValueError('postprocess/remove_background must be booleans')
    if postprocess:
        _validate_grid(grid_width, grid_height)
        _validate_palette(palette_colors)
        _validate_export_scale(export_scale)
        if remove_background:
            _parse_hex_color(background_color or '')
    reference = _safe_path(reference_path) if reference_path is not None else None
    ref_sha = None
    if reference is not None:
        _image_facts(reference)  # validate before allocating a GPU attempt
        ref_sha = _sha256_file(reference)
    with _generation_lock():
        if _comfyui_check_queue():
            raise RuntimeError('ComfyUI queue is not empty; no attempt submitted')
        # Any unresolved local job may still be using the backend, even if its
        # timeout has elapsed. Never bypass it by creating a new lineage.
        for path in _Path(_safe_path('results/jobs')).glob('*.json'):
            with path.open(encoding='utf-8') as handle:
                old = json.load(handle)
            if old.get('status') in ['pending', 'submitting', 'running', 'unknown']:
                raise RuntimeError('An unresolved local job requires reconciliation: ' + old['job_id'])
        job = _reserve_attempt(kind, model, ref_sha, retry_of_job_id)
        job_id = job['job_id']
        directory = _safe_path(f'results/jobs/{job_id}')
        os.mkdir(directory)  # IDs may never reuse a result directory
        job.update({'adapter': adapter.capabilities(), 'prompt': prompt, 'seed': seed, 'postprocess': postprocess,
                    'parameters': {'grid_width': grid_width, 'grid_height': grid_height,
                                   'palette_colors': palette_colors, 'export_scale': export_scale,
                                   'remove_background': remove_background, 'background_color': background_color}})
        _save_job(job_id, job)
        submitted = False
        terminal = False
        start = time.monotonic()
        try:
            if reference is not None:
                copied = os.path.join(directory, 'reference.png')
                with open(reference, 'rb') as src, open(copied, 'xb') as dest:
                    dest.write(src.read())
                if _sha256_file(copied) != ref_sha:
                    raise ValueError('Reference changed during copy')
                job.update({'reference_path': reference_path,
                            'reference_copy_path': os.path.relpath(copied, _WORK_ROOT),
                            'reference_resource_id': 'sha256:' + ref_sha})
                uploaded = _comfyui_upload_image(copied)
                graph = adapter.build_graph(prompt, seed, uploaded)
            else:
                graph = adapter.build_graph(prompt, seed)
            graph['9']['inputs']['filename_prefix'] = 'pavlusha-sprites/' + job_id
            _write_json(os.path.join(directory, 'api_graph.json'), graph)
            job['status'] = 'submitting'
            _save_job(job_id, job)
            submitted = True  # connection loss can hide an accepted backend job
            prompt_id = _comfyui_submit(graph)
            job.update({'prompt_id': prompt_id, 'status': 'running'})
            _save_job(job_id, job)
            history = _comfyui_poll(prompt_id, COMFYUI_GENERATION_TIMEOUT)
            terminal = True
            _write_json(os.path.join(directory, 'history.json'), history)
            raw = os.path.join(directory, 'raw.png')
            _comfyui_download_image(history, raw)
            raw_info = {'raw_path': os.path.relpath(raw, _WORK_ROOT), 'raw_sha256': _sha256_file(raw),
                        'resource_id': uuid.uuid4().hex, 'image': _image_facts(raw)}
            job.update(raw_info)
            job['result'] = dict(raw_info)
            if postprocess:
                processed = sprite_pixelize(raw_info['raw_path'], grid_width, grid_height,
                                            palette_colors, export_scale, remove_background, background_color)
                job['revisions'].append({'kind': 'raw', 'result': dict(raw_info)})
                job['result'] = {**raw_info, **processed}
            # Backend success records execution only. Alpha and view acceptance
            # stay separate, including when generation returns an opaque image.
            job.update({'status': 'success', 'elapsed_seconds': round(time.monotonic()-start, 3),
                        'completed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
            _save_job(job_id, job)
        except Exception as exc:
            terminal = terminal or isinstance(exc, _BackendFailure)
            job['status'] = 'unknown' if submitted and not terminal else 'failed'
            job['errors'].append({'code': type(exc).__name__, 'message': str(exc)})
            job['elapsed_seconds'] = round(time.monotonic()-start, 3)
            _save_job(job_id, job)
            # Return a recorded failure, rather than losing IDs inside an exception.
        finally:
            if terminal:
                try:
                    job['cleanup'] = _comfyui_release()
                    job['cleanup_requested'] = job['cleanup']['free_requested']
                    job['cleanup_confirmed'] = True
                except Exception as exc:
                    job['cleanup'] = getattr(exc, 'evidence', {'status':'blocked', 'error':str(exc)})
                    job['cleanup_requested'] = job['cleanup'].get('free_requested', False)
                    job['cleanup_confirmed'] = False
                _save_job(job_id, job)
        return sprite_result(job_id)


def sprite_generate(prompt: str, model: str = 'qwen21_turbo', seed: int = 42,
                    postprocess: bool = False, grid_width: int = 64, grid_height: int = 64,
                    palette_colors: int = 32, export_scale: int = 4,
                    remove_background: bool = False, background_color: Optional[str] = None,
                    retry_of_job_id: Optional[str] = None) -> dict:
    """Generate with the selected adapter; raw by default. Retry latest lineage job explicitly, maximum 3 attempts.

    The workshop owns GPU coordination and the adapter confirms ComfyUI cleanup.
    """
    return _run_generation('generate', prompt, model, seed, postprocess, grid_width, grid_height,
                           palette_colors, export_scale, remove_background, background_color,
                           None, retry_of_job_id)


def sprite_edit(reference_path: str, prompt: str, seed: int = 42, postprocess: bool = False,
                grid_width: int = 64, grid_height: int = 64, palette_colors: int = 32,
                export_scale: int = 4, remove_background: bool = False,
                background_color: Optional[str] = None, retry_of_job_id: Optional[str] = None,
                model: str = 'qwen21_turbo') -> dict:
    """Edit with the selected adapter and pinned image reference; explicit bounded retries, raw preserved.

    The workshop owns GPU coordination and preserves the pinned input reference.
    """
    if not isinstance(reference_path, str) or not reference_path:
        raise ValueError('reference_path must be a non-empty relative path')
    return _run_generation('edit', prompt, model, seed, postprocess, grid_width, grid_height,
                           palette_colors, export_scale, remove_background, background_color,
                           reference_path, retry_of_job_id)


def sprite_status(job_id: str) -> dict:
    """Read local recorded job state. Unknown is not failure and is never retried automatically."""
    job = _load_job(job_id)
    if job is None:
        raise ValueError('Job not found')
    return {key: job.get(key) for key in ['job_id', 'type', 'status', 'model', 'lineage_id',
            'attempt_id', 'attempt_index', 'retry_of_job_id', 'prompt_id', 'errors', 'acceptance']}


def sprite_result(job_id: str) -> dict:
    """Read execution result and independent acceptance state, retaining IDs even on failure."""
    job = _load_job(job_id)
    if job is None:
        raise ValueError('Job not found')
    result = {key: value for key, value in job.items() if key not in ['result', 'revisions']}
    result.update(job.get('result', {}))
    result['revisions'] = job.get('revisions', [])
    return result


def _client():
    return _package.comfy_client.ComfyClient(COMFYUI_BASE_URL,COMFYUI_READ_TIMEOUT,COMFYUI_POLL_INTERVAL)

def _comfyui_request(method,path,body=None):
    return _client().request(method,path,body)

def _comfyui_check_queue():
    return _client().check_queue()

def _comfyui_submit(graph):
    return _client().submit(graph)

def _comfyui_poll(prompt_id,timeout):
    return _client().poll(prompt_id,timeout)

def _comfyui_download_image(history,dest_path):
    return _client().download_image(history,dest_path)

def _comfyui_upload_image(path):
    return _client().upload_image(path)

def _comfyui_free():
    return _client().free()

def _image_facts(path):
    return _processing.inspect_image(path)

def _pixelize_image(input_path,grid_width,grid_height,palette_colors,export_scale,
                    remove_background,background_color,result_dir=None):
    return _processing.pixelize(input_path,_WORK_ROOT,grid_width,grid_height,palette_colors,
                               export_scale,remove_background,background_color,result_dir)


def _comfyui_release():
    unresolved = []
    for metadata in _Path(_JOBS_DIR).glob('*.json'):
        job = json.loads(metadata.read_text())
        if job.get('status') in ['pending', 'submitting', 'running', 'unknown']:
            unresolved.append(job)
    return _client().release_resources(unresolved)
