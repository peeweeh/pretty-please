"""SkillSwarm — executes multiple skills against the same user_message in
parallel dependency waves.

Wave 0 = skills with no unresolved deps.
Wave N = skills whose deps are all in waves 0..N-1.

Inside each wave: ThreadPoolExecutor so independent skills run concurrently
against Bedrock. We use threads (not asyncio) because the whole demo path
is synchronous boto3. Cost on Bedrock is unchanged; wall-clock is better.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


def build_waves(
    skill_ids: list[str], deps: dict[str, list[str]]
) -> list[list[str]]:
    """Topologically partition skill_ids into dependency waves.

    deps[skill_id] -> list of skill_id it depends on. Unknown skills are
    dropped silently (same forgiveness as SkillLoader)."""
    requested = [sid for sid in skill_ids if sid in deps]
    resolved: set[str] = set()
    waves: list[list[str]] = []
    remaining = list(requested)

    # Safety ceiling — prevents infinite loop on a cyclic graph.
    for _ in range(len(requested) + 1):
        if not remaining:
            break
        ready = [
            sid for sid in remaining
            if all(d in resolved or d not in deps for d in deps[sid])
        ]
        if not ready:
            # Cyclic dep or unresolvable — flush the rest as a final wave
            # so the demo doesn't deadlock.
            waves.append(list(remaining))
            break
        waves.append(ready)
        resolved.update(ready)
        remaining = [sid for sid in remaining if sid not in resolved]
    return waves


def run_swarm(
    skill_ids: list[str],
    deps: dict[str, list[str]],
    runner: Callable[[str, dict], dict],
    upstream: dict,
    max_workers: int = 4,
) -> dict:
    """Execute each wave in parallel, thread-per-skill.

    Args:
        skill_ids:  ordered list of skill_ids the caller wants run.
        deps:       dep graph (usually skill_id -> skill.dependencies).
        runner:     callable(skill_id, upstream_results) -> result dict.
        upstream:   static base payload (e.g. user_message) passed as
                    upstream_results on wave 0.
        max_workers: thread pool size per wave.

    Returns:
        {
          "waves": [
             {"wave": 0, "skills": [...], "elapsed_ms": ..., "results": {sid: {...}}},
             ...
          ],
          "total_elapsed_ms": ...,
          "results": {sid: result_dict},
        }
    """
    waves = build_waves(skill_ids, deps)
    t0 = time.time()
    wave_reports: list[dict] = []
    accumulated: dict = dict(upstream)

    for idx, wave in enumerate(waves):
        wt0 = time.time()
        wave_results: dict[str, dict] = {}
        if len(wave) == 1:
            sid = wave[0]
            wave_results[sid] = runner(sid, dict(accumulated))
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {
                    ex.submit(runner, sid, dict(accumulated)): sid for sid in wave
                }
                for fut in futures:
                    sid = futures[fut]
                    wave_results[sid] = fut.result()
        accumulated.update(wave_results)
        wave_reports.append(
            {
                "wave": idx,
                "skills": list(wave),
                "elapsed_ms": int((time.time() - wt0) * 1000),
                "results": wave_results,
            }
        )

    return {
        "waves": wave_reports,
        "total_elapsed_ms": int((time.time() - t0) * 1000),
        "results": {
            sid: r for w in wave_reports for sid, r in w["results"].items()
        },
    }
