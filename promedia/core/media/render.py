"""EDL to ffmpeg (T-041).

Compiles an edit into a single ffmpeg invocation. One invocation rather than a
chain of intermediate files is deliberate: intermediates cost a re-encode each,
and every re-encode loses quality and time. A filter graph does the whole edit
in one pass.

The compilation is a pure function of the EDL and the resolved source paths, so
it is testable without running ffmpeg at all — and it is, because a filter graph
is exactly the kind of string-built artefact where an error is invisible until
something segfaults at the far end.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ffmpeg
from .edl import EDL, Clip, TextOverlay

# ffmpeg filter fragments per named effect. Kept here, next to the compiler, so
# that adding an effect to the EDL vocabulary and teaching the compiler to
# render it are the same edit rather than two that can drift apart.
EFFECT_FILTERS: dict[str, str] = {
    "none": "",
    "grayscale": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "blur": "boxblur=4:1",
    "sharpen": "unsharp=5:5:1.0",
    "brighten": "eq=brightness=0.12",
    "darken": "eq=brightness=-0.12",
    "saturate": "eq=saturation=1.5",
}

# Where named positions land, as ffmpeg x/y expressions. Expressions rather
# than numbers so they hold at any output resolution (see TextOverlay).
TEXT_POSITIONS: dict[str, str] = {
    "top": "x=(w-text_w)/2:y=h*0.08",
    "center": "x=(w-text_w)/2:y=(h-text_h)/2",
    "bottom": "x=(w-text_w)/2:y=h*0.85-text_h/2",
}

QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    # Measured on this machine, 60s of 1490x1022 -> 1280x720 with fade + text.
    "fast":     {"encoder": "libx264", "args": ["-preset", "veryfast", "-crf", "23"]},
    "balanced": {"encoder": "libx264", "args": ["-preset", "medium", "-crf", "21"]},
    "quality":  {"encoder": "libx264", "args": ["-preset", "slow", "-crf", "18"]},
    # Roughly half the file size of x264 at comparable speed here. Default for
    # delivery; not a speed optimisation (the filter chain is CPU-bound anyway).
    "hardware": {"encoder": "h264_qsv", "args": ["-global_quality", "24"]},
}


@dataclass(frozen=True)
class RenderPlan:
    """A compiled render, inspectable before it is executed.

    Returned rather than run so the agent can show an operator what WILL happen,
    and so tests can assert the graph without a 30-second encode.
    """

    args: list[str]
    filter_graph: str
    output_path: Path
    width: int
    height: int
    quality: str
    source_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "resolution": f"{self.width}x{self.height}",
            "quality": self.quality,
            "sources": self.source_count,
            "filter_graph": self.filter_graph,
        }


def _clip_chain(index: int, clip: Clip, width: int, height: int) -> str:
    """The video filter chain for one clip, ending at label [vN]."""
    steps = [
        # Scale into the target frame preserving aspect, then pad the remainder.
        # force_original_aspect_ratio=decrease + pad is what stops a vertical
        # render from stretching landscape footage into a distortion.
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
        "setsar=1",
    ]
    if clip.speed != 1.0:
        steps.append(f"setpts={1.0 / clip.speed:.6f}*PTS")
    effect = EFFECT_FILTERS.get(clip.effect, "")
    if effect:
        steps.append(effect)
    if clip.transition_in in ("fade", "dissolve") and clip.transition_duration > 0:
        # A fade from black at the head of the clip. True cross-dissolves
        # between clips need xfade, which requires absolute timeline offsets;
        # this is the honest subset that works with concat.
        steps.append(f"fade=t=in:st=0:d={clip.transition_duration:g}")
    return f"[{index}:v]" + ",".join(steps) + f"[v{index}]"


def _audio_chain(index: int, clip: Clip) -> str:
    steps = []
    if clip.speed != 1.0:
        # atempo is limited to 0.5-2.0 per instance, so a larger change is
        # chained. Without this, speeds outside that range are silently ignored
        # by ffmpeg and the audio desynchronises from the video.
        remaining = clip.speed
        while remaining > 2.0:
            steps.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            steps.append("atempo=0.5")
            remaining /= 0.5
        steps.append(f"atempo={remaining:.6f}")
    volume = 0.0 if clip.mute else clip.volume
    if volume != 1.0:
        steps.append(f"volume={volume:g}")
    steps.append("aresample=48000")
    steps.append("aformat=sample_fmts=fltp:channel_layouts=stereo")
    return f"[{index}:a]" + ",".join(steps) + f"[a{index}]"


def _text_filter(overlay: TextOverlay, font: Path | None, text_path: Path) -> str:
    """One drawtext, reading its text from a SIDECAR FILE rather than inline.

    This is the single most-tested decision in this module, because inline text
    could not be made to work reliably. Captions come from humans and from the
    agent, so they contain apostrophes, colons and percent signs as a matter of
    course, and ffmpeg's filtergraph quoting could not survive them:

      * a colon splits filter arguments, so it must be escaped;
      * an apostrophe TERMINATES the quoted section — a backslash does not
        escape it inside quotes, and close-escape-reopen fails too;
      * a percent triggers strftime expansion, which escaping cannot prevent
        because expansion happens after unescaping.

    Measured: inline text failed on every caption containing both a colon and
    an apostrophe ("Q1: revenue +12% (it's up)"), and the failure was not even
    reported against drawtext — the broken quote swallowed the chain separator,
    so ffmpeg complained about a `loudnorm` option instead. ``textfile=`` passes
    all of them because the content never enters the graph at all.
    """
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(overlay.text, encoding="utf-8")
    parts = [
        ffmpeg.font_argument(font),
        f"textfile='{ffmpeg.escape_path_for_filter(text_path)}'",
        # Belt and braces: the text is out of the graph, but drawtext would
        # still expand a '%' read from the file.
        "expansion=none",
        f"fontsize={overlay.size}",
        f"fontcolor={overlay.color}",
        TEXT_POSITIONS[overlay.position],
    ]
    if overlay.box:
        parts.append("box=1:boxcolor=black@0.5:boxborderw=12")
    if overlay.start or overlay.end is not None:
        end = overlay.end if overlay.end is not None else 99999
        parts.append(f"enable='between(t,{overlay.start:g},{end:g})'")
    return "drawtext=" + ":".join(parts)


def compile_render(
    edl: EDL,
    sources: dict[str, Path],
    output_path: Path,
    *,
    quality: str = "balanced",
    font: Path | None = None,
    workspace: Path | None = None,
) -> RenderPlan:
    """Turn an EDL plus resolved source paths into an ffmpeg command line.

    ``sources`` maps asset id to file path; the caller resolves them, because
    resolving an asset means checking rights and availability and that is not
    this module's business.

    ``workspace`` holds the caption sidecar files (see _text_filter). It
    defaults to a directory beside the output, so a caller that does not care
    need not think about it, and one that does — a temp dir in tests, a project
    scratch dir in production — can say so.
    """
    edl.validate()
    if quality not in QUALITY_PRESETS:
        from ...errors import ValidationError

        raise ValidationError(
            f"unknown quality '{quality}'", parameter="quality",
            supported=sorted(QUALITY_PRESETS),
        )
    width, height = edl.resolution()

    # Input order is fixed here and referenced by index throughout the graph.
    ordered_ids: list[str] = []
    for clip in edl.clips:
        ordered_ids.append(clip.asset_id)
    audio_offset = len(ordered_ids)
    for track in edl.audio:
        ordered_ids.append(track.asset_id)

    args: list[str] = []
    for position, clip in enumerate(edl.clips):
        path = sources[clip.asset_id]
        # -ss before -i seeks by keyframe and is fast; -t bounds the read. Both
        # placed as INPUT options so ffmpeg decodes only the needed span rather
        # than the whole file and discarding most of it.
        args += ["-ss", f"{clip.start:g}"]
        if clip.end is not None:
            args += ["-t", f"{max(0.0, clip.end - clip.start):g}"]
        args += ["-i", str(path)]
    for track in edl.audio:
        args += ["-i", str(sources[track.asset_id])]

    chains: list[str] = []
    for index, clip in enumerate(edl.clips):
        chains.append(_clip_chain(index, clip, width, height))
        chains.append(_audio_chain(index, clip))

    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(edl.clips)))
    chains.append(f"{concat_inputs}concat=n={len(edl.clips)}:v=1:a=1[vcat][acat]")

    video_label = "vcat"
    if edl.text:
        scratch = workspace or (output_path.parent / f".{output_path.stem}-text")
        text_filters = ",".join(
            _text_filter(overlay, font, scratch / f"text_{index}.txt")
            for index, overlay in enumerate(edl.text)
        )
        chains.append(f"[{video_label}]{text_filters}[vtxt]")
        video_label = "vtxt"

    audio_label = "acat"
    for position, track in enumerate(edl.audio):
        input_index = audio_offset + position
        steps = [f"volume={track.volume:g}", "aresample=48000",
                 "aformat=sample_fmts=fltp:channel_layouts=stereo"]
        if track.fade_in > 0:
            steps.append(f"afade=t=in:st=0:d={track.fade_in:g}")
        chains.append(f"[{input_index}:a]" + ",".join(steps) + f"[bg{position}]")
        # duration=first keeps a long music bed from extending the video past
        # its last frame, which is the default and is almost never wanted.
        chains.append(f"[{audio_label}][bg{position}]amix=inputs=2:duration=first:"
                      f"dropout_transition=0[amix{position}]")
        audio_label = f"amix{position}"

    if edl.normalise_audio:
        # Single-pass loudness normalisation to broadcast target. The most
        # valuable audio step available and the one most often skipped.
        chains.append(f"[{audio_label}]loudnorm=I=-16:TP=-1.5:LRA=11[anorm]")
        audio_label = "anorm"

    filter_graph = ";".join(chains)
    preset = QUALITY_PRESETS[quality]

    args += [
        "-filter_complex", filter_graph,
        "-map", f"[{video_label}]",
        "-map", f"[{audio_label}]",
        "-c:v", preset["encoder"], *preset["args"],
        "-pix_fmt", "yuv420p",  # without this, some players show nothing at all
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    return RenderPlan(
        args=args, filter_graph=filter_graph, output_path=output_path,
        width=width, height=height, quality=quality, source_count=len(ordered_ids),
    )


def execute(plan: RenderPlan, *, timeout_seconds: float) -> dict[str, Any]:
    """Run a compiled plan and report what came out.

    The output is probed rather than assumed: ffmpeg can exit 0 having written
    a file that is not playable, and reporting a successful render of a broken
    file is the media equivalent of a fabricated result.
    """
    plan.output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg.run(plan.args, timeout_seconds=timeout_seconds)
    if not plan.output_path.is_file() or plan.output_path.stat().st_size == 0:
        raise ffmpeg.RenderFailed(
            "ffmpeg reported success but produced no output file",
            output_path=str(plan.output_path),
        )
    info = ffmpeg.probe(plan.output_path)
    if not info.has_video:
        raise ffmpeg.RenderFailed(
            "the rendered file contains no video stream",
            output_path=str(plan.output_path),
        )
    return {
        "output_path": str(plan.output_path),
        "byte_size": info.byte_size,
        "duration_seconds": info.duration_seconds,
        "width": info.width,
        "height": info.height,
        "video_codec": info.video_codec,
        "audio_codec": info.audio_codec,
        "quality": plan.quality,
    }
