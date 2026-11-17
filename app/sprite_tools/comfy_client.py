"""ComfyUI HTTP transport shared by adapters; no model loading on import."""
import json,os,time,uuid,urllib.request,urllib.error,urllib.parse
from typing import Optional,Dict,List

class _BackendFailure(RuntimeError):
    pass


class ResourceCleanupFailure(RuntimeError):
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = dict(evidence, error=message)


class ComfyClient:
    def __init__(self, base_url, read_timeout=30, poll_interval=2):
        self.base_url=base_url.rstrip("/")
        self.read_timeout=read_timeout
        self.poll_interval=poll_interval

    def request(self, method: str, path: str, body: Optional[Dict] = None) -> Dict:
        url = self.base_url + path
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.read_timeout) as resp:
                body = resp.read().decode("utf-8")
                if not body.strip():
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as e:
            body_bytes = e.read()
            try:
                err = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                err = {"error": body_bytes.decode("utf-8", errors="replace")[:500]}
            raise RuntimeError(f"ComfyUI HTTP {e.code}: {err}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"ComfyUI connection failed: {e.reason}") from None


    def check_queue(self) -> List[Dict]:
        result = self.request("GET", "/queue")
        return result.get("queue_running", []) + result.get("queue_pending", [])


    def submit(self, prompt_graph: Dict) -> str:
        body = {"prompt": prompt_graph}
        result = self.request("POST", "/prompt", body)
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return prompt_id: {result}")
        return prompt_id


    def poll(self, prompt_id: str, timeout: int) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = self.request('GET', '/history/' + urllib.parse.quote(prompt_id, safe=''))
            entry = history.get(prompt_id)
            if entry:
                state = entry.get('status', {})
                if state.get('status_str') == 'error':
                    raise _BackendFailure(json.dumps(entry, ensure_ascii=False))
                if state.get('completed') and state.get('status_str') == 'success':
                    return entry
            time.sleep(self.poll_interval)
        raise TimeoutError('Generation state unresolved after timeout; do not retry automatically')


    def download_image(self, output_info: Dict, dest_path: str) -> str:
        outputs = output_info.get("outputs", {})
        for node_id, node_out in outputs.items():
            images = node_out.get("images", [])
            if images:
                img = images[0]
                filename = img.get("filename", "")
                subfolder = img.get("subfolder", "")
                folder_type = img.get("type", "output")
                url = self.base_url + "/view?" + urllib.parse.urlencode({"filename":filename,"subfolder":subfolder,"type":folder_type})
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=self.read_timeout) as resp:
                    data = resp.read()
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "xb") as f:
                    f.write(data)
                return dest_path
        raise RuntimeError("No output images found in ComfyUI history entry")


    def upload_image(self, file_path: str) -> str:
        """Upload image to ComfyUI via multipart POST /upload/image.
        Returns the filename assigned by ComfyUI for use in LoadImage node."""
        filename = os.path.basename(file_path)
        boundary = '----Pavlusha' + uuid.uuid4().hex[:16]
        CRLF = chr(13) + chr(10)

        with open(file_path, 'rb') as f:
            file_data = f.read()

        header_parts = [
            '--' + boundary + CRLF,
            'Content-Disposition: form-data; name="overwrite"' + CRLF + CRLF,
            'false' + CRLF,
            '--' + boundary + CRLF,
            'Content-Disposition: form-data; name="image"; filename="' + filename + '"' + CRLF,
            'Content-Type: image/png' + CRLF + CRLF,
        ]
        header = ''.join(header_parts).encode('utf-8')
        footer = (CRLF + '--' + boundary + '--' + CRLF).encode('utf-8')
        body = header + file_data + footer

        url = self.base_url + '/upload/image'
        req = urllib.request.Request(
            url, data=body,
            headers={'Content-Type': 'multipart/form-data; boundary=' + boundary},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=self.read_timeout) as resp:
                result = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')[:500]
            raise RuntimeError('ComfyUI upload failed HTTP %d: %s' % (e.code, err_body)) from None
        except urllib.error.URLError as e:
            raise RuntimeError('ComfyUI upload connection failed: %s' % str(e.reason)) from None

        uploaded_name = result.get('name')
        if not uploaded_name:
            raise RuntimeError('ComfyUI upload did not return filename: %s' % str(result))
        return "/".join(x for x in [result.get("subfolder"), uploaded_name] if x)


    def free(self) -> bool:
        try:
            self.request("POST", "/free", {"unload_models": True, "free_memory": True})
            return True
        except Exception:
            return False

    def release_resources(self, unresolved_jobs=(), *, max_used_mib=1900,
                          expected_devices=2, timeout=60):
        """Own ComfyUI cleanup through confirmation, independently of the LLM runtime.

        Limits describe this host; the caller supplies local unresolved job records.
        Never interrupt queued work, kill processes, or assume HTTP200 freed VRAM.
        """
        import subprocess
        evidence = {'status': 'blocked', 'checked_at': time.time(), 'free_requested': False}
        try:
            for job in unresolved_jobs:
                prompt_id = job.get('prompt_id')
                if not prompt_id:
                    raise RuntimeError('Unresolved job without prompt_id: ' + job['job_id'])
                history = self.request('GET', '/history/' + urllib.parse.quote(prompt_id, safe=''))
                state = history.get(prompt_id, {}).get('status', {})
                if state.get('status_str') != 'error' and not (state.get('status_str') == 'success' and state.get('completed')):
                    raise RuntimeError('Backend job is not confirmed terminal: ' + job['job_id'])
            if self.check_queue():
                raise RuntimeError('ComfyUI queue is busy; no unload or LLM restore')
            if not self.free():
                raise RuntimeError('ComfyUI /free failed')
            evidence['free_requested'] = True
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                result = subprocess.run(['nvidia-smi', '--query-gpu=index,memory.used',
                                         '--format=csv,noheader,nounits'],
                                        capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    raise RuntimeError('Cannot measure GPU memory')
                values = {}
                for line in result.stdout.splitlines():
                    index, used = line.split(',')
                    values[index.strip()] = int(used.strip())
                evidence['gpu_memory_mib'] = values
                if len(values) == expected_devices and max(values.values()) < max_used_mib:
                    if self.check_queue():
                        raise RuntimeError('ComfyUI queue changed during cleanup')
                    evidence.update(status='ready', max_used_mib=max_used_mib)
                    return evidence
                time.sleep(1)
            raise RuntimeError('GPU memory did not fall below the configured cleanup ceiling')
        except Exception as exc:
            raise ResourceCleanupFailure(str(exc), evidence) from exc
