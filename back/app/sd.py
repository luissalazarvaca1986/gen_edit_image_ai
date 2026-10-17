"""Ejecución de sd-cli (stable-diffusion.cpp) como subproceso."""
import asyncio
import os
import re
from collections import deque

SD_CLI = os.environ.get("SD_CLI", "sd-cli")
PROGRESS_RE = re.compile(r"\|\s*(\d+)/(\d+)\s*-")


class SdError(Exception):
    pass


async def run(*, model_path, prompt, negative_prompt, width, height, steps, cfg_scale, seed, sampler,
              output_path, init_image=None, strength=None, on_progress=None):
    args = [
        SD_CLI,
        "-m", model_path,
        "-p", prompt,
        "-W", str(width), "-H", str(height),
        "--steps", str(steps),
        "--cfg-scale", str(cfg_scale),
        "--seed", str(seed),
        "--sampling-method", sampler,
        "-o", output_path,
    ]
    if negative_prompt:
        args += ["-n", negative_prompt]
    if init_image:
        args += ["-i", init_image, "--strength", str(strength)]

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    tail = deque(maxlen=15)
    buf = ""
    # La barra de progreso se reescribe con \r, así que se parte por \r y \n
    while chunk := await proc.stdout.read(4096):
        buf += chunk.decode(errors="replace")
        *lines, buf = re.split(r"[\r\n]", buf)
        for line in lines:
            line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).strip()
            if not line:
                continue
            m = PROGRESS_RE.search(line)
            if m and on_progress:
                on_progress(int(m.group(1)), int(m.group(2)))
            elif not m:
                tail.append(line)
    code = await proc.wait()
    if code != 0 or not os.path.exists(output_path):
        raise SdError(f"sd-cli terminó con código {code}:\n" + "\n".join(tail))
