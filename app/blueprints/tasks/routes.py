from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Team, Project, Task, TaskMessage, Agent, MASTER_AGENT_TEMPLATE
import json
import re
import logging
import html as html_module

logger = logging.getLogger(__name__)

# === Parser for blocks/parts when reading chat - DB has no HTML tags, parsed when reading and shown as accordion ===
# No HTML tags inside DB, only raw markdown with ``` code blocks. Parsed when reading.

def _find_file_paths_in_text(text):
    if not text:
        return []
    patterns = [
        r'→\s*`?(/workspace/[^\s`\)"]+)`?',
        r'File to create:\s*→?\s*`?(/workspace/[^\s`\)"]+)`?',
        r'\*\*File to create:\*\*\s*\*\*→\s*`?(/workspace/[^\s`\)"]+)`?\*\*',
        r'#\s*File:\s*(/workspace/[^\s\n]+)',
        r'#\s*Path:\s*(/workspace/[^\s\n]+)',
        r'<!--\s*File:\s*(\/workspace\/[^\s\n]+)\s*-->',
        r'//\s*File:\s*(\/workspace\/[^\s\n]+)',
        r'/\*\s*File:\s*(\/workspace\/[^\s\n\*]+)\s*\*/',
        r'^###\s*(/workspace/[^\s\(\)]+)',
        r'"remote_path":\s*"(/workspace/[^"]+)"',
    ]
    found = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.MULTILINE):
            p = m.group(1).strip().strip('`"\'`)').replace('-->','').strip()
            found.append(p)
    seen = set()
    uniq = []
    for p in found:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq

def _detect_backend_read_path(text_before):
    """Path from a backend Sandbox Reads header right above the fence, e.g.
    ### /workspace/index.html (167 chars)  or
    ### read_file_from_sandbox({"remote_path": "/workspace/index.html"}) -> ...
    The fence holds that file's known content, so it gets a green panel + Exec."""
    if not text_before:
        return None
    tail = text_before[-400:]
    # tool-evidence header with explicit remote_path JSON wins (most specific)
    m = None
    for mm in re.finditer(r'"remote_path":\s*"(/workspace/[^"]+)"', tail):
        m = mm
    if m:
        return m.group(1)
    # plain reads header: last ### /workspace/... in the tail
    for mm in re.finditer(r'^###\s*(/workspace/[^\s\(\)]+)', tail, flags=re.MULTILINE):
        m = mm
    if m:
        return m.group(1).strip()
    return None


def _detect_file_path_explicit(code, text_before, file_paths_from_text, block_idx):
    """Only when code block itself contains # File: /workspace/... - per user: only do div when there's ```html # File: /workspace/contact.html
    Also handles typo worksapce, worspace, workpace, workpsace -> workspace (user reported # File: /worksapce/item.html)
    Plus backend Sandbox Reads headers (path known even without a marker)."""
    if not code:
        return None
    # Correct typo in code string for file path detection (worksapce -> workspace)
    code_for_search = code.replace('/worksapce/', '/workspace/').replace('/worspace/', '/workspace/').replace('/workpace/', '/workspace/').replace('/workpsace/', '/workspace/')
    # Also check text_before for typo? No, only code itself per new strict rule, but we also correct typo in path
    patterns = [
        r'#\s*(?:File|Path):\s*(/workspace/[^\s\n`]+)',
        r'<!--\s*File:\s*(\/workspace\/[^\s\n]+)\s*-->',
        r'//\s*File:\s*(\/workspace\/[^\s\n]+)',
        r'/\*\s*File:\s*(\/workspace\/[^\s\n\*]+)\s*\*/',
        # Typo variants that should be corrected
        r'#\s*(?:File|Path):\s*(/worksapce/[^\s\n`]+)',
        r'#\s*(?:File|Path):\s*(/worspace/[^\s\n`]+)',
        r'#\s*(?:File|Path):\s*(/workpace/[^\s\n`]+)',
        r'<!--\s*File:\s*(\/worksapce\/[^\s\n]+)\s*-->',
        r'<!--\s*File:\s*(\/worspace\/[^\s\n]+)\s*-->',
    ]
    for pat in patterns:
        m = re.search(pat, code_for_search)
        if m:
            path = m.group(1).strip().strip('`"\'`)')
            # Correct typo in returned path
            path = path.replace('/worksapce/', '/workspace/').replace('/worspace/', '/workspace/').replace('/workpace/', '/workspace/').replace('/workpsace/', '/workspace/')
            return path
    # Backend-known path (Sandbox Reads header right above the fence)
    backend = _detect_backend_read_path(text_before)
    if backend:
        return backend.replace('/worksapce/', '/workspace/').replace('/worspace/', '/workspace/').replace('/workpace/', '/workspace/').replace('/workpsace/', '/workspace/')
    return None

def _detect_file_path_for_block(code, text_before, file_paths_from_text, block_idx, task_id, message_id):
    explicit = _detect_file_path_explicit(code, text_before, file_paths_from_text, block_idx)
    if explicit:
        return explicit
    # Fallback for execution endpoint (still need generic path to write file even if no explicit File: comment)
    remote = f"/workspace/tasks/{task_id}/message_{message_id}_{block_idx}.py"
    lower = (code or "").lower()
    if "<html" in lower or "<!doctype" in lower:
        remote = f"/workspace/tasks/{task_id}/message_{message_id}_{block_idx}.html"
        for fp in file_paths_from_text or []:
            if fp.endswith('.html'):
                remote = fp
                break
    elif "function" in code and "{" in code:
        remote = f"/workspace/tasks/{task_id}/message_{message_id}_{block_idx}.js"
    return remote

def _strip_file_marker(code):
    """Strip # File: /workspace/... line from code - should not be part of code (user request #1)"""
    if not code:
        return code
    lines = code.split("\n")
    if not lines:
        return code
    first = lines[0].strip()
    # Patterns that indicate file marker line should be removed from code content
    file_marker_patterns = [
        r'^#\s*(?:File|Path):\s*/(?:workspace|worksapce|worspace|workpace|workpsace)/.*$',
        r'^<!--\s*File:\s*/(?:workspace|worksapce|worspace|workpace|workpsace)/.*-->$',
        r'^//\s*File:\s*/(?:workspace|worksapce|worspace|workpace|workpsace)/.*$',
        r'^/\*\s*File:\s*/(?:workspace|worksapce|worspace|workpace|workpsace)/.*\*/$',
        r'^File to create:\s*→?\s*`?/(?:workspace|worksapce|worspace|workpace|workpsace)/.*$',
    ]
    for pat in file_marker_patterns:
        if re.match(pat, first):
            # Remove first line
            return "\n".join(lines[1:]).lstrip()
    return code

def _clean_text(text):
    """Remove whitespaces - collapse multiple blank lines, strip leading/trailing whitespace"""
    if not text:
        return ""
    # Strip leading/trailing whitespace
    t = text.strip()
    # Collapse 3+ newlines into 2 newlines (remove excessive empty space that causes big gaps between panels)
    t = re.sub(r'\n\s*\n\s*\n+', '\n\n', t)
    # Remove trailing spaces on each line
    t = "\n".join([line.rstrip() for line in t.split("\n")])
    # Collapse multiple spaces (but keep indentation for code? For plain text panels, we collapse)
    # For plain panels, we want single spaces, but keep as is for now
    return t.strip()


def _strip_briefing_prefix(text):
    """Chat bubbles show the message body only: drop a leading Briefing: label.

    The LLM request template prefixes user content with 'Briefing: ...' and
    stored content may keep '**Briefing:** ...'. Only the text after the
    prefix is shown in the timeline; the full prompt stays behind + button.
    """
    if not text:
        return text
    t = text.lstrip()
    m = re.match(r'^\*\*Briefing:\*\*\s*(.*)$', t, flags=re.DOTALL)
    if m:
        return m.group(1).lstrip()
    m = re.match(r'^Briefing:\s*(.*)$', t, flags=re.DOTALL)
    if m:
        return m.group(1).lstrip()
    return text

def _parse_code_blocks(text):
    if not text:
        return []
    pattern = r"```[^\n]*\n([\s\S]*?)```"
    blocks = []
    for m in re.finditer(pattern, text):
        code = m.group(1)
        # Remove leading/trailing whitespace from code block itself? Keep internal formatting but strip outer
        code = code.strip('\n')
        start = m.start()
        end = m.end()
        text_before = text[max(0, start-800):start]
        blocks.append({"code": code, "start": start, "end": end, "text_before": text_before})
    triple_count = text.count("```")
    if triple_count % 2 == 1:
        # Find last ``` opening that is unclosed - improved to stop at next file marker or header, not go to end
        # This fixes bot#99 discount.html which had unclosed ```html block followed by ## Verification without closing ```
        last_triple_idx = text.rfind("```")
        if last_triple_idx != -1:
            # Get language line
            after_triple = text[last_triple_idx:]
            # Match ```lang\n
            um_match = re.match(r"```[^\n]*\n", after_triple)
            if um_match:
                code_start = last_triple_idx + len(um_match.group(0))
                code_remaining = text[code_start:]
                # Look for next file marker or header that indicates end of this unclosed code block
                # Markers that should stop code block: **File to create:, ## Verification, ## , etc.
                stop_markers = ["\n**File to create:", "\n## Verification", "\n## ", "\n---", "\n### "]
                stop_idx = len(code_remaining)
                for marker in stop_markers:
                    idx = code_remaining.find(marker)
                    if idx != -1 and idx < stop_idx and idx > 50:  # must be at least 50 chars of code before marker
                        stop_idx = idx
                code = code_remaining[:stop_idx].strip('\n')
                if code and len(code) > 30 and not any(b["code"] == code for b in blocks):
                    if any(x in code.lower() for x in ["<html", "<!doctype", "function", "{", "<style", "<script", "--", ":root", "body{", "html{"]) or len(code) > 80:
                        blocks.append({"code": code, "start": code_start, "end": code_start + len(code), "text_before": text[max(0, code_start-800):code_start]})
    return blocks

def _render_text_with_green_code_inside(text, message_id, task_id, team_slug, project_slug, global_offset_start=0):
    """Render text where code blocks become green divs inside plain panel. Removes whitespaces to fix big gaps. LLM Response not green, only code inside green."""
    if not text:
        return ""
    # Remove excessive whitespaces - collapse multiple blank lines, strip
    cleaned_text = _clean_text(text)
    code_blocks = _parse_code_blocks(cleaned_text)
    if not code_blocks:
        # No code blocks, return plain cleaned text
        return f'<div style="white-space:pre-wrap; color:var(--text); font-size:11px; line-height:1.4;">{html_module.escape(cleaned_text[:12000])}</div>'

    parts = []
    last_idx = 0
    for local_idx, block in enumerate(code_blocks):
        global_idx = global_offset_start + local_idx
        # Text before block - plain, not green, remove whitespaces, small margin to avoid big gaps
        text_before = cleaned_text[last_idx:block["start"]]
        text_before_clean = _clean_text(text_before)
        if text_before_clean:
            parts.append(f'<div style="white-space:pre-wrap; margin:2px 0; color:var(--text); font-size:11px; line-height:1.4; background:transparent; padding:2px 0;">{html_module.escape(text_before_clean[:1500])}</div>')

        code = block["code"].strip()
        # Strip # File: line from code - should not be part of code (user request)
        code_stripped = _strip_file_marker(code)
        file_path = _detect_file_path_explicit(code, block.get("text_before",""), None, global_idx)
        if file_path and file_path.startswith("/workspace/"):
            file_name = file_path.split("/")[-1]
            code_esc = html_module.escape(code_stripped[:25000])
            parts.append(f'''
              <div class="code-block-item mb-2" style="background:#0a0f0a; border:1px solid #10b981; border-radius:6px; overflow:hidden; margin:2px 0;">
                <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 8px; background:rgba(16,185,129,0.15); border-bottom:1px solid #10b981;">
                  <code style="font-size:10px; background:#0f0f17; padding:2px 6px; border-radius:4px; color:#86efac; border:1px solid rgba(16,185,129,0.3);">{html_module.escape(file_path)}</code>
                  <div style="display:flex; gap:6px;">
                    <button class="btn btn-sm" onclick="navigator.clipboard.writeText(this.parentElement.parentElement.nextElementSibling.textContent).then(()=>{{this.innerHTML='✅ Copied'; setTimeout(()=>{{this.innerHTML='Copy';}},2000)}})" style="font-size:10px; background:var(--bg3); border:1px solid var(--border); color:var(--text); padding:2px 6px; border-radius:4px;">Copy</button>
                    <button class="btn btn-sm exec-block-btn" data-message-id="{message_id}" data-block-idx="{global_idx}" data-team-slug="{team_slug}" data-project-slug="{project_slug}" data-task-id="{task_id}" data-remote-path="{html_module.escape(file_path)}" style="font-size:10px; background:#10b981; color:white; border:none; padding:2px 6px; border-radius:4px;">Exec → {html_module.escape(file_name)}</button>
                  </div>
                </div>
                <pre style="margin:0; padding:8px; background:#0f1410; color:#86efac; font-family:JetBrains Mono, monospace; font-size:11px; white-space:pre-wrap; word-break:break-all; line-height:1.4;"><code style="color:#86efac;">{code_esc}</code></pre>
              </div>
            ''')
        else:
            # Code without an explicit /workspace/ path is NOT a sandbox file:
            # render neutral (no green) so Agent Information and plain snippets
            # never look like executable file panels. Green is reserved for
            # explicit-path file blocks with an Exec button above.
            code_esc = html_module.escape(code[:4000])
            parts.append(f'''
              <div class="code-block-item mb-2" style="background:var(--bg2); border:1px solid var(--border); border-radius:6px; overflow:hidden; margin:2px 0;">
                <div style="padding:2px 6px; background:var(--bg3); border-bottom:1px solid var(--border); font-size:9px; color:var(--text-dim);"><i class="bi bi-code"></i> Code snippet</div>
                <pre style="margin:0; padding:8px; background:#0f0f17; color:var(--text); font-family:JetBrains Mono, monospace; font-size:11px; white-space:pre-wrap; line-height:1.4;"><code>{code_esc}</code></pre>
              </div>
            ''')
        last_idx = block["end"]
    after = cleaned_text[last_idx:]
    after_clean = _clean_text(after)
    if after_clean:
        parts.append(f'<div style="white-space:pre-wrap; margin:6px 0; color:var(--text-dim); font-size:11px;">{html_module.escape(after[:2000])}</div>')
    return "\n".join(parts)

def render_code_blocks_html(text, message_id, task_id, team_slug, project_slug, file_paths_combined=None, global_offset=0, is_full_prompt=False):
    """Only divs where there's code starting with ```html # File: /workspace/... - green text + exec button"""
    if not text:
        return ""
    if file_paths_combined is None:
        file_paths_combined = _find_file_paths_in_text(text)
    blocks = _parse_code_blocks(text)
    if not blocks:
        return ""

    html_parts = []
    for local_idx, block in enumerate(blocks):
        global_idx = global_offset + local_idx
        file_path = _detect_file_path_explicit(block["code"], block.get("text_before",""), None, global_idx)
        if not file_path or not file_path.startswith("/workspace/"):
            continue
        # Strip # File: line from code - should not be part of code (user request #1)
        code_clean = _strip_file_marker(block["code"])
        file_name = file_path.split("/")[-1]
        code_esc = html_module.escape(code_clean[:25000].strip())
        html_parts.append(f'''
          <div class="code-block-item mb-2" style="background:#0a0f0a; border:1px solid #10b981; border-radius:6px; overflow:hidden; margin:2px 0;">
            <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 8px; background:rgba(16,185,129,0.15); border-bottom:1px solid #10b981;">
              <div style="display:flex; align-items:center; gap:6px; font-size:11px; flex:1; min-width:0;">
                <i class="bi bi-file-code" style="color:#10b981; font-size:12px;"></i>
                <span style="color:#10b981; font-weight:bold; font-size:11px;">{html_module.escape(file_name)}</span>
                <code style="font-size:10px; background:#0f0f17; padding:2px 6px; border-radius:3px; color:#86efac; border:1px solid rgba(16,185,129,0.3); max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="{html_module.escape(file_path)}">{html_module.escape(file_path)}</code>
              </div>
              <button class="btn btn-sm exec-block-btn" data-message-id="{message_id}" data-block-idx="{global_idx}" data-team-slug="{team_slug}" data-project-slug="{project_slug}" data-task-id="{task_id}" data-remote-path="{html_module.escape(file_path)}" style="font-size:10px; background:#10b981; border:none; color:white; padding:3px 8px; border-radius:4px; font-weight:bold; margin-left:6px;">
                <i class="bi bi-play-fill"></i> Exec
              </button>
            </div>
            <pre style="margin:0; padding:8px; max-height:500px; overflow:auto; font-size:11px; line-height:1.4; background:#0f1410; color:#86efac; white-space:pre-wrap; word-break:break-all; font-family:'JetBrains Mono', monospace;"><code style="color:#86efac;">{code_esc}</code></pre>
          </div>
        ''')
    return "".join(html_parts)  # No newline gaps, remove whitespaces between divs

def render_full_prompt_collapsible_html(text, message_id, task_id, team_slug, project_slug):
    """Collapsible panels: Agent Information (until ## Briefing Input), Briefing Input + Full Prompt plain, LLM Response full plain with code inside green, and file panels with title [Name of file] eg: /workspace/contact.html, exec + copy + green code div"""
    if not text:
        return ""

    all_blocks = _parse_code_blocks(text)
    file_blocks = []
    for idx, block in enumerate(all_blocks):
        fp = _detect_file_path_explicit(block["code"], block.get("text_before",""), None, idx)
        if fp and fp.startswith("/workspace/"):
            file_blocks.append({"path": fp, "code": block["code"], "global_idx": idx, "file_name": fp.split("/")[-1], "start": block["start"]})

    # Split sections
    briefing_idx = text.find("## Briefing Input")
    if briefing_idx == -1:
        briefing_idx = text.find("Briefing Input")

    # Remove whitespaces - per user: when parsing you need to remove the whitespaces
    def _clean(t):
        return _clean_text(t)

    if briefing_idx != -1 and briefing_idx > 0:
        agent_info_text = _clean(text[:briefing_idx])
    else:
        # Find first major header as end of agent info
        first_headers = []
        for marker in ["## Full Prompt", "## Skills Active", "## System Prompt", "## LLM Response", "## Execution Plan"]:
            idx = text.find(marker)
            if idx != -1:
                first_headers.append(idx)
        agent_info_text = _clean(text[:min(first_headers)] if first_headers else text[:2000])

    # Briefing + Full Prompt panel
    briefing_panel_text = ""
    if briefing_idx != -1:
        search_start = briefing_idx + len("## Briefing Input")
        next_markers = ["## Skills Active", "## System Prompt", "### Model Info", "## Model Info", "## LLM Response", "## Execution Plan", "## Generated Code"]
        next_idx = len(text)
        for marker in next_markers:
            idx = text.find(marker, search_start)
            if idx != -1 and idx < next_idx:
                next_idx = idx
        briefing_panel_text = _clean(text[briefing_idx:next_idx])
    else:
        fp_idx = text.find("## Full Prompt")
        if fp_idx != -1:
            next_idx = len(text)
            for marker in ["## Skills Active", "## System Prompt", "## LLM Response", "## Execution Plan"]:
                idx = text.find(marker, fp_idx+10)
                if idx != -1 and idx < next_idx:
                    next_idx = idx
            briefing_panel_text = _clean(text[fp_idx:next_idx])

    # LLM Response panel
    llm_response_text = ""
    llm_idx = text.find("## LLM Response")
    if llm_idx != -1:
        first_file_start = None
        for b in all_blocks:
            if _detect_file_path_explicit(b["code"], b.get("text_before",""), None, 0):
                first_file_start = b["start"]
                break
        if first_file_start is not None and first_file_start > llm_idx:
            llm_response_text = _clean(text[llm_idx:first_file_start])
        else:
            llm_response_text = _clean(text[llm_idx:])
    else:
        briefing_end = 0
        if briefing_idx != -1 and briefing_panel_text:
            briefing_end = briefing_idx + len(briefing_panel_text)
        else:
            briefing_end = len(agent_info_text) if 'agent_info_text' in locals() else 0
        first_file_start = None
        for b in all_blocks:
            if _detect_file_path_explicit(b["code"], b.get("text_before",""), None, 0):
                first_file_start = b["start"]
                break
        if first_file_start is not None:
            # Need original text positions, but we have cleaned, so use original text slicing then clean
            # Find raw llm text then clean
            raw_llm = text[briefing_end:first_file_start] if first_file_start is not None else text[briefing_end:]
            llm_response_text = _clean(raw_llm)
        else:
            raw_llm = text[briefing_end:]
            llm_response_text = _clean(raw_llm)

    def esc(t):
        return html_module.escape(t or "")[:15000]

    accordion_id = f"fullprompt-{message_id}"
    html_parts = []
    html_parts.append(f'<div class="accordion" id="{accordion_id}" style="display:flex; flex-direction:column; gap:2px; border-radius:8px; overflow:hidden;">')

    if agent_info_text and agent_info_text.strip():
        agent_inner = _render_text_with_green_code_inside(agent_info_text, message_id, task_id, team_slug, project_slug, global_offset_start=0)
        html_parts.append(f'''
          <div class="accordion-item" style="background:var(--bg2); border:1px solid var(--border); margin:0; border-radius:0;">
            <h2 class="accordion-header" id="heading-agent-{message_id}" style="margin:0;">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-agent-{message_id}" aria-expanded="false" aria-controls="collapse-agent-{message_id}" style="background:var(--bg3); color:var(--text); font-weight:bold; font-size:12px; padding:8px 12px; border-radius:0;">
                <i class="bi bi-person-badge" style="margin-right:6px;"></i> Agent Information (until ## Briefing Input) - {len(agent_info_text)} chars
              </button>
            </h2>
            <div id="collapse-agent-{message_id}" class="accordion-collapse collapse" aria-labelledby="heading-agent-{message_id}" data-bs-parent="#{accordion_id}">
              <div class="accordion-body" style="background:#0f0f17; color:var(--text-dim); font-family:JetBrains Mono, monospace; font-size:11px; padding:8px; max-height:400px; overflow:auto;">
                {agent_inner}
              </div>
            </div>
          </div>
        ''')

    if briefing_panel_text and briefing_panel_text.strip():
        briefing_inner = _render_text_with_green_code_inside(briefing_panel_text, message_id, task_id, team_slug, project_slug, global_offset_start=0)
        html_parts.append(f'''
          <div class="accordion-item" style="background:var(--bg2); border:1px solid var(--border); margin:0; border-radius:0;">
            <h2 class="accordion-header" id="heading-briefing-{message_id}" style="margin:0;">
              <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-briefing-{message_id}" aria-expanded="false" aria-controls="collapse-briefing-{message_id}" style="background:var(--bg3); color:var(--text); font-weight:bold; font-size:12px; padding:8px 12px; border-radius:0;">
                <i class="bi bi-file-text" style="margin-right:6px;"></i> Briefing Input + Full Prompt - plain
              </button>
            </h2>
            <div id="collapse-briefing-{message_id}" class="accordion-collapse collapse" aria-labelledby="heading-briefing-{message_id}" data-bs-parent="#{accordion_id}">
              <div class="accordion-body" style="background:#0f0f17; color:var(--text); font-family:JetBrains Mono, monospace; font-size:11px; padding:8px; max-height:500px; overflow:auto;">
                {briefing_inner}
              </div>
            </div>
          </div>
        ''')

    if llm_response_text and llm_response_text.strip():
        llm_inner = _render_text_with_green_code_inside(llm_response_text, message_id, task_id, team_slug, project_slug, global_offset_start=0)
        html_parts.append(f'''
          <div class="accordion-item" style="background:var(--bg2); border:1px solid var(--border); margin:0; border-radius:0;">
            <h2 class="accordion-header" id="heading-llm-{message_id}" style="margin:0;">
              <button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-llm-{message_id}" aria-expanded="true" aria-controls="collapse-llm-{message_id}" style="background:rgba(16,185,129,0.08); color:var(--text); font-weight:bold; font-size:12px; padding:8px 12px; border-radius:0;">
                <i class="bi bi-robot" style="margin-right:6px; color:#10b981;"></i> LLM Response (full) - {len(llm_response_text)} chars - plain, code inside green
              </button>
            </h2>
            <div id="collapse-llm-{message_id}" class="accordion-collapse collapse show" aria-labelledby="heading-llm-{message_id}" data-bs-parent="#{accordion_id}">
              <div class="accordion-body" style="background:#0f0f17; color:var(--text); font-family:JetBrains Mono, monospace; font-size:11px; padding:8px; max-height:600px; overflow:auto;">
                {llm_inner}
              </div>
            </div>
          </div>
        ''')

    html_parts.append('</div>')

    if file_blocks:
        # Just keep div id="file-panel" - remove [Name of file] eg: ... exec + copy, green color header per user request
        # User: "the line above 'Files to Create (1) – [Name of file] eg: /workspace/contact.html, exec + copy, green code' already tell what file, you can remove [name of file] .. balb bla bla exec + copy, green color. just keep the div id 'file-panel'."
        for fb in file_blocks:
            path = fb["path"]
            # Correct typo worksapce -> workspace
            path = path.replace('/worksapce/', '/workspace/').replace('/worspace/', '/workspace/').replace('/workpace/', '/workspace/').replace('/workpsace/', '/workspace/')
            file_name = path.split("/")[-1]
            # Strip file marker line from code - should not be part of code (user request #1)
            code_clean = _strip_file_marker(fb["code"])
            code_esc = html_module.escape(code_clean[:25000].strip())
            block_uid = f"file-{message_id}-{fb['global_idx']}"
            html_parts.append(f'''
              <div id="file-panel" class="file-panel mb-2" style="background:#0a0f0a; border:1px solid #10b981; border-radius:6px; overflow:hidden; margin:2px 0;">
                <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 8px; background:rgba(16,185,129,0.15); border-bottom:1px solid #10b981;">
                  <code style="font-size:10px; background:#0f0f17; padding:2px 6px; border-radius:4px; color:#86efac; border:1px solid rgba(16,185,129,0.3); max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="{html_module.escape(path)}">{html_module.escape(path)}</code>
                  <div style="display:flex; gap:6px;">
                    <button class="btn btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('{block_uid}').textContent).then(()=>{{this.innerHTML='✅ Copied'; setTimeout(()=>{{this.innerHTML='Copy';}},2000)}})" style="font-size:10px; background:var(--bg3); border:1px solid var(--border); color:var(--text); padding:2px 6px; border-radius:4px;">
                      <i class="bi bi-clipboard"></i> Copy
                    </button>
                    <button class="btn btn-sm exec-block-btn" data-message-id="{message_id}" data-block-idx="{fb['global_idx']}" data-team-slug="{team_slug}" data-project-slug="{project_slug}" data-task-id="{task_id}" data-remote-path="{html_module.escape(path)}" style="font-size:10px; background:#10b981; border:none; color:white; padding:3px 8px; border-radius:4px; font-weight:bold;">
                      <i class="bi bi-play-fill"></i> Exec
                    </button>
                  </div>
                </div>
                <pre id="{block_uid}" style="margin:0; padding:8px; max-height:600px; overflow:auto; font-size:11px; line-height:1.4; background:#0f1410; color:#86efac; white-space:pre-wrap; word-break:break-all; font-family:'JetBrains Mono', monospace;"><code style="color:#86efac;">{code_esc}</code></pre>
              </div>
            ''')

    return "\n".join(html_parts)

tasks_bp = Blueprint('tasks', __name__)

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/create', methods=['GET', 'POST'])
@login_required
def create(team_slug, project_slug):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()  # briefing
        full_prompt = request.form.get('full_prompt', '').strip()
        status = request.form.get('status', 'todo')
        priority = request.form.get('priority', 'medium')
        if not title:
            flash('Title required', 'danger')
            return redirect(url_for('tasks.create', team_slug=team.slug, project_slug=project.slug))
        # position at end
        max_pos = db.session.query(db.func.max(Task.position)).filter_by(project_id=project.id).scalar() or 0
        task = Task(
            title=title,
            description=description,
            full_prompt=full_prompt,
            status=status,
            priority=priority,
            project_id=project.id,
            creator_id=current_user.id,
            assignee_id=current_user.id,
            position=max_pos+1
        )
        db.session.add(task)
        db.session.flush()
        # Create initial briefing message in chat timeline
        if description or full_prompt:
            msg = TaskMessage(
                task_id=task.id,
                user_id=current_user.id,
                role='briefing',
                content=description or title,
                full_prompt=full_prompt,
                message_type='briefing'
            )
            db.session.add(msg)
        db.session.commit()
        flash(f'Task \"{title}\" created', 'success')
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))
    return render_template('tasks/create.html', team=team, project=project)

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>')
@login_required
def view(team_slug, project_slug, task_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    messages = task.messages.order_by(TaskMessage.created_at.asc()).all()
    agents = task.agents.order_by(Agent.created_at.desc()).all()
    master_skills = MASTER_AGENT_TEMPLATE['skills']

    # Project sandbox info for Task Details sidebar (1 per project for now, but design supports multiples)
    try:
        from app.models import ProjectSandbox, ProjectActivity
        project_sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()
        # Also get all sandboxes for project (future: multiples)
        project_sandboxes = ProjectSandbox.query.filter_by(project_id=project.id).all()
        # Recent activities for cross-task visibility (server restarting from other task)
        recent_activities = ProjectActivity.query.filter_by(project_id=project.id).order_by(ProjectActivity.created_at.desc()).limit(5).all()
    except Exception as e:
        project_sandbox = None
        project_sandboxes = []
        recent_activities = []

    # For @ mention autocomplete: project agents (excluding current task) + team members
    try:
        from app.models import User
        team_members = team.members.all()
        # All agents in same project but different tasks
        project_agents_all = Agent.query.join(Task, Agent.task_id == Task.id).filter(Task.project_id == project.id).order_by(Agent.created_at.desc()).all()
        current_ids = [a.id for a in agents]
        # Unique by name, excluding current task agents
        seen = set([a.name.lower() for a in agents])
        project_agents = []
        for pa in project_agents_all:
            if pa.task_id != task.id and pa.name.lower() not in seen:
                seen.add(pa.name.lower())
                project_agents.append(pa)

        # Build JSON for frontend
        in_task_data = [{"id": a.id, "name": a.name, "role": a.role, "type": "agent", "in_task": True, "avatar": a.name[0].upper()} for a in agents]
        in_project_data = [{"id": a.id, "name": a.name, "role": a.role, "type": "agent", "in_task": False, "source_task_id": a.task_id, "avatar": a.name[0].upper()} for a in project_agents]
        people_data = [{"id": u.id, "username": u.username, "display_name": u.display_name or u.username, "type": "user", "avatar": (u.display_name or u.username)[0].upper()} for u in team_members]

        mention_data = {
            "inTask": in_task_data,
            "inProject": in_project_data,
            "people": people_data
        }
    except Exception as e:
        logger.warning(f"Mention data build failed: {e}")
        team_members = []
        project_agents = []
        mention_data = {"inTask": [], "inProject": [], "people": []}
        project_sandbox = None
        project_sandboxes = []
        recent_activities = []

    # Server-side rendering - DB has no HTML tags, parsed when reading and shown as accordion
    # Break chat into parts and show them as accordion: agent info, briefing+full plain, llm response, file panels with green code + exec+copy
    try:
        for msg in messages:
            try:
                full_text = msg.full_prompt or ""
                content_text = _strip_briefing_prefix(msg.content or "")
                combined_text = full_text + "\n" + content_text
                file_paths_combined = _find_file_paths_in_text(combined_text)

                full_blocks = _parse_code_blocks(full_text)
                # Collapsible panels for full prompt
                msg.rendered_full_prompt = render_full_prompt_collapsible_html(
                    full_text,
                    message_id=msg.id,
                    task_id=task.id,
                    team_slug=team.slug,
                    project_slug=project.slug
                )
                # Content (briefing) - only explicit file path blocks as green divs
                msg.rendered_content = render_code_blocks_html(
                    content_text,
                    message_id=msg.id,
                    task_id=task.id,
                    team_slug=team.slug,
                    project_slug=project.slug,
                    file_paths_combined=file_paths_combined,
                    global_offset=len(full_blocks),
                    is_full_prompt=False
                )
                if not msg.rendered_content or not msg.rendered_content.strip():
                    msg.rendered_content = f'<div style="white-space:pre-wrap; color:var(--text);">{html_module.escape(content_text)}</div>' if content_text else ""
                msg.code_blocks_count = len(full_blocks) + len(_parse_code_blocks(content_text))
                msg.file_paths = file_paths_combined
            except Exception as inner_e:
                logger.warning(f"Failed to render code blocks for message {msg.id}: {inner_e}")
                msg.rendered_content = f'<div style="white-space:pre-wrap;">{html_module.escape(_strip_briefing_prefix(msg.content or ""))}</div>' if msg.content else ""
                try:
                    msg.rendered_full_prompt = render_full_prompt_collapsible_html(
                        msg.full_prompt or "",
                        message_id=msg.id,
                        task_id=task.id,
                        team_slug=team.slug,
                        project_slug=project.slug
                    )
                except:
                    msg.rendered_full_prompt = f'<div style="white-space:pre-wrap; background:#0f0f17; border:1px solid var(--border); border-radius:8px; padding:12px; font-family:JetBrains Mono; font-size:11px;">{html_module.escape(msg.full_prompt or "")[:8000]}</div>' if msg.full_prompt else ""
                msg.code_blocks_count = 0
                msg.file_paths = []
    except Exception as e:
        logger.warning(f"Server-side code block rendering failed: {e}")

    return render_template('tasks/view.html', team=team, project=project, task=task, messages=messages, agents=agents, master_skills=master_skills, master_agent=MASTER_AGENT_TEMPLATE, team_members=team_members, project_agents=project_agents, mention_data=mention_data, project_sandbox=project_sandbox, project_sandboxes=project_sandboxes, recent_activities=recent_activities)

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(team_slug, project_slug, task_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    if request.method == 'POST':
        task.title = request.form.get('title', task.title)
        task.description = request.form.get('description', task.description)
        task.full_prompt = request.form.get('full_prompt', task.full_prompt)
        task.status = request.form.get('status', task.status)
        task.priority = request.form.get('priority', task.priority)
        db.session.commit()
        flash('Task updated', 'success')
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))
    return render_template('tasks/edit.html', team=team, project=project, task=task)

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete(team_slug, project_slug, task_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted', 'info')
    return redirect(url_for('projects.view', team_slug=team.slug, project_slug=project.slug))

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/message', methods=['POST'])
@login_required
def add_message(team_slug, project_slug, task_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    
    content = request.form.get('content', '').strip()
    full_prompt = request.form.get('full_prompt', '').strip()
    message_type = request.form.get('message_type', 'chat')
    agent_id = request.form.get('agent_id')
    role = request.form.get('role', 'user')
    
    if not content:
        flash('Message content required', 'danger')
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))
    
    msg = TaskMessage(
        task_id=task.id,
        user_id=current_user.id if role=='user' else None,
        agent_id=int(agent_id) if agent_id else None,
        role=role,
        content=content,
        full_prompt=full_prompt if full_prompt else None,
        message_type=message_type
    )
    db.session.add(msg)
    db.session.flush()

    # === REQUEST LOGGING AS CODE (user wants to see logs when creating/sending) ===
    request_log = {
        "task_id": task.id,
        "project": f"{team.slug}/{project.slug}",
        "message_id": msg.id,
        "content": content,
        "full_prompt": full_prompt,
        "role": role,
        "message_type": message_type,
        "user_id": current_user.id,
        "agent_id": agent_id,
        "read_by_agents": [a.name for a in task.agents.all()]
    }
    log_code = f"""# REQUEST LOG - Add Message to Task Chat
# Task: {task.title} (ID {task.id})
# Project: {team.slug}/{project.slug}
# From: {current_user.username} (role={role})

import requests

payload = {json.dumps(request_log, indent=2)}

# POST /projects/team/{team.slug}/{project.slug}/tasks/{task.id}/message
# Response: message_id={msg.id}, broadcasted to {task.agents.count()} bots

# All bots in this task have now read it:
# {', '.join([a.name for a in task.agents.all()])}

print(f"Message {{payload['message_id']}} added and read by {{len(payload['read_by_agents'])}} bots")
"""
    print(log_code)  # Console log
    logger.info(f"Chat message added: task={task.id} msg={msg.id} by {current_user.username}: {content[:100]}")

    # Broadcast: all other bots in task read this chat
    try:
        msg.broadcast_to_task_agents(exclude_agent_id=int(agent_id) if agent_id else None)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Fallback still commit message even if broadcast fails
        db.session.add(msg)
        db.session.commit()
    
    # === AUTO-REPLY WHEN MENTIONED (any bot, generic) ===
    auto_replies = []
    try:
        if role == 'user':  # Only auto-reply to user messages, not agent->agent to avoid loops
            # Detect mentioned agents by name
            content_lower = content.lower()
            mentioned_agents = []
            for agent in task.agents.all():
                # Skip if this message is from the agent itself
                if agent_id and int(agent_id) == agent.id:
                    continue
                # Check variants: full name, name without _bot, first part, role
                name_variants = [
                    agent.name.lower(),
                    agent.name.lower().replace('_', ' ').replace('-', ' '),
                    agent.name.lower().replace('_bot','').replace('_', '').strip(),
                    agent.name.lower().split('_')[0],
                    agent.name.lower().split(' ')[0],
                ]
                # Add role-based mention too? e.g., "task2 Specialist"
                # For custom bots, also check base name without _bot suffix
                for variant in name_variants:
                    if variant and len(variant) >= 3 and variant in content_lower:
                        mentioned_agents.append(agent)
                        break
                # Also check if content contains @agentname
                if f"@{agent.name.lower()}" in content_lower and agent not in mentioned_agents:
                    mentioned_agents.append(agent)

            # Limit to max 2 auto-replies to avoid spam
            mentioned_agents = mentioned_agents[:2]
            newly_added_agents = []
            newly_added_people = []

            # === CLONE AGENTS FROM PROJECT IF NOT IN CURRENT TASK (user wants: if not had agent, add to task/chat channel) ===
            # Find agents in same project but different tasks whose name matches mention
            try:
                from sqlalchemy import and_
                project_agents = Agent.query.join(Task, Agent.task_id == Task.id).filter(
                    Task.project_id == task.project_id,
                    Task.id != task.id
                ).all()
                # Deduplicate by name
                seen_names = set([a.name.lower() for a in task.agents.all() + mentioned_agents])
                for proj_agent in project_agents:
                    if len(newly_added_agents) >= 2:
                        break
                    # Check if its name matches content and not already in current task
                    proj_name_lower = proj_agent.name.lower()
                    if proj_name_lower in content_lower and proj_name_lower not in seen_names:
                        # Clone without reselecting skills (keep original skills)
                        cloned = Agent.create_clone(
                            task_id=task.id,
                            name=proj_agent.name,
                            role=proj_agent.role,
                            custom_skills=proj_agent.get_skills(),  # Keep original skills, not reselect
                            custom_prompt=proj_agent.system_prompt
                        )
                        db.session.add(cloned)
                        db.session.flush()
                        # New bot reads all previous chats
                        from app.models import MessageRead
                        for prev_msg in task.messages.all():
                            if not MessageRead.query.filter_by(message_id=prev_msg.id, agent_id=cloned.id).first():
                                db.session.add(MessageRead(message_id=prev_msg.id, agent_id=cloned.id))
                        # System message about adding via mention
                        join_msg = TaskMessage(
                            task_id=task.id,
                            agent_id=cloned.id,
                            role='system',
                            content=f"Agent cloned: {cloned.name} ({cloned.role}) via @ mention from other task • {len(cloned.get_skills())} skills (kept original) • added to chat",
                            full_prompt=f"Cloned from project agent {proj_agent.name} (ID {proj_agent.id}) via @ mention '{content[:100]}'\nOriginal task: {proj_agent.task_id}\nSkills kept: {[s.get('name') for s in cloned.get_skills()]}",
                            message_type='log'
                        )
                        db.session.add(join_msg)
                        db.session.flush()
                        join_msg.broadcast_to_task_agents()
                        newly_added_agents.append(cloned)
                        seen_names.add(proj_name_lower)
                        mentioned_agents.append(cloned)  # Also auto-reply from newly added
                        logger.info(f"Cloned agent from project via mention: {cloned.name} from task {proj_agent.task_id} to {task.id}")

                # === ADD PEOPLE (team members) TO TASK PARTICIPANTS ===
                # If @ mentions a person not in task participants, add them
                team_members = team.members.all()
                for member in team_members:
                    if member.id == current_user.id:
                        continue  # Don't add self
                    username_variants = [
                        member.username.lower(),
                        (member.display_name or "").lower(),
                        f"@{member.username.lower()}",
                    ]
                    for variant in username_variants:
                        if variant and len(variant) >= 3 and variant in content_lower:
                            # Check if already participant
                            if task.participants.filter_by(id=member.id).first() is None and member.id != task.creator_id and member.id != (task.assignee_id or -1):
                                task.participants.append(member)
                                newly_added_people.append(member.username)
                                # System message
                                people_msg = TaskMessage(
                                    task_id=task.id,
                                    user_id=current_user.id,
                                    role='system',
                                    content=f"👤 {member.display_name or member.username} (@{member.username}) added to task via @ mention",
                                    full_prompt=f"User {current_user.username} mentioned @{member.username} in message {msg.id}\nAdded to task_participants table\nContent: {content[:200]}",
                                    message_type='log'
                                )
                                db.session.add(people_msg)
                                db.session.flush()
                                people_msg.broadcast_to_task_agents()
                                logger.info(f"Added person {member.username} to task {task.id} via @ mention")
                            break

            except Exception as e:
                logger.warning(f"Project agent/people clone via mention failed: {e}")

            if mentioned_agents:
                from app.services.modal_client import run_agent_factory
                for mentioned_agent in mentioned_agents:
                    # Set agent to working (thinking icon)
                    mentioned_agent.status = 'working'
                    try:
                        mentioned_agent.update_heartbeat()
                    except:
                        pass
                    db.session.commit()

                    # Log request as code for auto-reply
                    auto_log = f"""# AUTO-REPLY TRIGGERED - Agent Mentioned
# User said: "{content[:100]}"
# Mentioned: {mentioned_agent.name} (ID {mentioned_agent.id})
# Reason: name '{mentioned_agent.name}' found in message
# All bots have read: {task.messages.count()} previous chats

from app.services.modal_client import run_agent_factory

task = Task.query.get({task.id})
agent = Agent.query.get({mentioned_agent.id})

# Context: full chat history, all bots have read
chat_history = \"\"\"{msg.content[:200]}...\"\"\"

result = run_agent_factory(task, agent, extra_context={{
    "triggered_by_mention": True,
    "mention_content": "{content[:100]}",
    "chat_history": chat_history
}})

# Save as TaskMessage -> appears in chat timeline with + toggle
"""
                    print(auto_log)
                    logger.info(f"Auto-reply triggered: {mentioned_agent.name} mentioned in msg {msg.id}")

                    result = run_agent_factory(task, mentioned_agent, extra_context={
                        "triggered_by_mention": True,
                        "mention_content": content,
                        "mention_message_id": msg.id,
                        "task_obj": task
                    })

                    reply_msg = TaskMessage(
                        task_id=task.id,
                        agent_id=mentioned_agent.id,
                        role='assistant',
                        content=result.get('briefing', f"{mentioned_agent.name} replied"),
                        full_prompt=f"# AUTO-REPLY - Mentioned by {current_user.username}\n# Trigger: '{content[:200]}'\n# Request as code:\n{auto_log}\n\n# Agent Response (full log):\n{result.get('full_log','')}",
                        message_type=result.get('message_type', 'chat')
                    )
                    db.session.add(reply_msg)
                    db.session.flush()
                    # Broadcast this auto-reply to all other bots
                    reply_msg.broadcast_to_task_agents()
                    reply_msg.mark_read_by_agent(mentioned_agent.id)
                    mentioned_agent.status = 'idle'
                    try:
                        mentioned_agent.update_heartbeat()
                    except:
                        pass
                    db.session.commit()
                    auto_replies.append(mentioned_agent.name)

                if auto_replies:
                    extra_info = []
                    if newly_added_agents:
                        extra_info.append(f"{len(newly_added_agents)} agent(s) added: {', '.join([a.name for a in newly_added_agents])}")
                    if newly_added_people:
                        extra_info.append(f"{len(newly_added_people)} people added: {', '.join(newly_added_people)}")
                    extra_str = f" ({'; '.join(extra_info)})" if extra_info else ""
                    flash(f'Message added + auto-reply from {", ".join(auto_replies)} (mentioned){extra_str} - all bots have read chats!', 'success')
                else:
                    flash(f'Message added - broadcasted to all {task.agents.count()} bots in task', 'success')
            else:
                # No agents mentioned, but maybe people/agents were added from project
                if newly_added_agents or newly_added_people:
                    extra_info = []
                    if newly_added_agents:
                        extra_info.append(f"{len(newly_added_agents)} agent(s) added")
                    if newly_added_people:
                        extra_info.append(f"{len(newly_added_people)} people added: {', '.join(newly_added_people)}")
                    flash(f'Message added + {"; ".join(extra_info)} via @ mention - broadcasted to all bots', 'success')
                else:
                    flash(f'Message added - broadcasted to all {task.agents.count()} bots in task', 'success')
        else:
            flash(f'Message added - broadcasted to all {task.agents.count()} bots in task', 'success')
    except Exception as e:
        logger.exception(f"Auto-reply failed: {e}")
        flash(f'Message added - broadcasted to all {task.agents.count()} bots (auto-reply error: {e})', 'warning')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return read info for UI
        read_count = msg.get_read_count()
        return jsonify({
            'success': True, 
            'message_id': msg.id, 
            'read_by': read_count, 
            'broadcast': f'All {task.agents.count()} bots have read it',
            'auto_replies': auto_replies,
            'request_log': log_code
        })
    return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/sync-reads', methods=['POST'])
@login_required
def sync_reads(team_slug, project_slug, task_id):
    """Ensure all bots have read all chats in task - broadcast sync"""
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    from app.models import MessageRead
    count = 0
    for msg in task.messages.all():
        for agent in task.agents.all():
            existing = MessageRead.query.filter_by(message_id=msg.id, agent_id=agent.id).first()
            if not existing:
                db.session.add(MessageRead(message_id=msg.id, agent_id=agent.id))
                count += 1
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'synced': count, 'message': f'Synced {count} read receipts - all {task.agents.count()} bots now have read all {task.messages.count()} chats'})
    flash(f'Synced {count} reads - all {task.agents.count()} bots have now read all chats', 'success')
    return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def update_status(team_slug, project_slug, task_id):
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    new_status = request.form.get('status') or request.json.get('status') if request.is_json else None
    if new_status in ['todo', 'in_progress', 'done', 'blocked']:
        task.status = new_status
        db.session.commit()
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'status': task.status})
    flash(f'Status updated to {task.status}', 'success')
    return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

@tasks_bp.route('/team/<team_slug>/<project_slug>/tasks/<int:task_id>/messages/<int:message_id>/execute', methods=['POST'])
@login_required
def execute_message_in_sandbox(team_slug, project_slug, task_id, message_id):
    """Execute chat message code in sandbox /workspace - makes changes to sandbox"""
    team = Team.query.filter_by(slug=team_slug).first_or_404()
    project = Project.query.filter_by(team_id=team.id, slug=project_slug).first_or_404()
    task = Task.query.filter_by(id=task_id, project_id=project.id).first_or_404()
    message = TaskMessage.query.filter_by(id=message_id, task_id=task.id).first_or_404()

    # Get project sandbox
    from app.models import ProjectSandbox, ProjectActivity
    sandbox = ProjectSandbox.query.filter_by(project_id=project.id).first()
    if not sandbox or not sandbox.modal_sandbox_id:
        # Use fallback mock id
        sandbox_id = f"sb-mock-{sandbox.name}-{project.id}" if sandbox else f"sb-mock-task-{task.id}"
        if not sandbox:
            # Create mock sandbox entry if none
            sandbox_id = f"sb-mock-task-{task.id}"
    else:
        sandbox_id = sandbox.modal_sandbox_id

    # Extract code using new parser - DB clean no HTML tags, parsed when reading
    # Only when explicit file path like # File: /workspace/contact.html - per user request
    text_to_search = (message.full_prompt or "") + "\n" + (message.content or "")
    file_paths_from_text = _find_file_paths_in_text(text_to_search)

    # Parse code blocks with any language (```html, ```python, whatever)
    all_parsed_blocks = _parse_code_blocks(text_to_search)

    # Helper to strip file marker line from code (delegates to module helper,
    # which also handles typo variants worksapce/worspace/workpace/workpsace)
    def _strip_file_marker_line(code):
        return _strip_file_marker(code)

    # Clean up code blocks - remove system prompt, keep only explicit file path blocks per user request: only when there's ```html # File: /workspace/contact.html
    filtered_blocks = []
    for cb in all_parsed_blocks:
        # cb is dict with "code" key from _parse_code_blocks
        code_content = cb["code"] if isinstance(cb, dict) else cb
        if not code_content:
            continue
        # Skip system prompt blocks
        if "You are CodeFactory Prime" in code_content and "<html" not in code_content.lower() and len(code_content) > 500:
            continue
        if len(code_content.strip()) < 10:
            continue
        # Only keep blocks that have explicit file path like # File: /workspace/contact.html inside code - per user request
        explicit_path = _detect_file_path_explicit(code_content, cb.get("text_before","") if isinstance(cb, dict) else "", file_paths_from_text, len(filtered_blocks))
        if not explicit_path or not explicit_path.startswith("/workspace/"):
            # Skip blocks without explicit file path - only divs where there's code starting with ```html # File: /workspace/...
            continue
        filtered_blocks.append(cb)

    # If after filtering no explicit file blocks, fallback to all blocks that have explicit path via text_before? Already filtered, so code_blocks = filtered_blocks
    # For execution, we want to execute only explicit file path blocks (green divs)
    code_blocks = filtered_blocks

    # Handle requested block_idx param - per-block exec button
    requested_block_idx = None
    try:
        if request.is_json:
            j = request.get_json(silent=True) or {}
            if 'block_idx' in j:
                requested_block_idx = int(j['block_idx'])
        if requested_block_idx is None:
            q = request.args.get('block_idx')
            if q is not None and str(q).lstrip('-').isdigit():
                requested_block_idx = int(q)
            else:
                q2 = request.form.get('block_idx')
                if q2 is not None and str(q2).lstrip('-').isdigit():
                    requested_block_idx = int(q2)
    except Exception:
        requested_block_idx = None

    # Determine which blocks to execute
    blocks_to_execute = []
    if requested_block_idx is not None:
        if 0 <= requested_block_idx < len(code_blocks):
            blocks_to_execute = [(requested_block_idx, code_blocks[requested_block_idx])]
        else:
            # Invalid idx - check if it's index in all_parsed_blocks (including non-explicit)? Try to find by global idx
            # For file panels, global_idx is index in all_blocks that have explicit path, but frontend sends global_idx from full_prompt+content combined
            # We should try to find block in all_parsed_blocks with explicit path at requested idx
            # For simplicity, if requested idx out of range for filtered_blocks but within all_parsed_blocks, try all_parsed_blocks
            if 0 <= requested_block_idx < len(all_parsed_blocks):
                cb = all_parsed_blocks[requested_block_idx]
                # Check if this block has explicit file path, if not, try to find explicit around
                explicit_path = _detect_file_path_explicit(cb["code"] if isinstance(cb, dict) else cb, cb.get("text_before","") if isinstance(cb, dict) else "", file_paths_from_text, requested_block_idx)
                if explicit_path:
                    blocks_to_execute = [(requested_block_idx, cb)]
                else:
                    blocks_to_execute = []
            else:
                blocks_to_execute = []
            if not blocks_to_execute:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
                    return jsonify({"error": f"Invalid block_idx {requested_block_idx}, only {len(code_blocks)} explicit file blocks found (with # File: /workspace/...)", "message_id": message_id, "total_blocks": len(code_blocks), "all_blocks": len(all_parsed_blocks)}), 400
                flash(f'Invalid block idx {requested_block_idx}, only {len(code_blocks)} explicit file blocks', 'danger')
                return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))
    else:
        blocks_to_execute = list(enumerate(code_blocks[:5]))

    # For each code block, write to sandbox /workspace - new files created if don't exist, strip # File: line, correct typo worksapce -> workspace
    results = []
    try:
        from app.services.modal_sandbox_service import write_text_to_sandbox
        import os, tempfile

        for idx, block in blocks_to_execute:
            # block is dict or string
            code = block["code"] if isinstance(block, dict) else block
            text_before = block.get("text_before","") if isinstance(block, dict) else ""

            # Determine file path - explicit only
            remote_path = _detect_file_path_explicit(code, text_before, file_paths_from_text, idx)
            if not remote_path:
                # Try file_paths_from_text by idx as fallback explicit
                if file_paths_from_text and idx < len(file_paths_from_text):
                    remote_path = file_paths_from_text[idx]
            if not remote_path:
                # Skip if no explicit path - per user request only when there's File: /workspace/...
                continue

            # Correct typo: worksapce, worspace, workpace, workpsace -> workspace (user reported # File: /worksapce/item.html)
            original_remote = remote_path
            remote_path = remote_path.replace('/worksapce/', '/workspace/').replace('/worspace/', '/workspace/').replace('/workpace/', '/workspace/').replace('/workpsace/', '/workspace/')
            if original_remote != remote_path:
                logger.info(f"Corrected typo in file path: {original_remote} -> {remote_path} (was misspelled)")

            # Strip # File: line from code - should not be part of code (user request #1)
            code_clean = _strip_file_marker_line(code)

            # Also correct typo inside code if file path comment had typo? Already stripped, but also ensure code doesn't contain worksapce in file references? Keep as is

            # Parent dirs are created inside write_text_to_sandbox_async via mkdir -p;
            # no separate exec helper exists (write service handles it internally).

            # Write to sandbox - real Modal only, new files created if don't exist (user: finally we can save files to modal sandbox)
            # remote_path already determined as explicit file path like /workspace/contact.html and typo corrected worksapce->workspace
            # code_clean already stripped of # File: line per user request #1

            # Ensure parent dirs exist and show trying feedback via logging (user request #2: should do something at least trying and showing it's creating file)
            logger.info(f"Trying to create file {remote_path} in sandbox {sandbox_id} - code length {len(code_clean)} - showing creating feedback")
            print(f"🧠 Trying to create file {remote_path} in sandbox {sandbox_id} - {len(code_clean)} chars - new file if not exists")

            from app.services.modal_sandbox_service import write_text_to_sandbox

            write_result = write_text_to_sandbox(sandbox_id, code_clean, remote_path)

            results.append({
                "remote_path": remote_path,
                "written": write_result.get('written', False),
                "mock": write_result.get('mock', False),
                "code_length": len(code_clean),
                "original_code_length": len(code),
                "stripped_file_marker": len(code) != len(code_clean)
            })

        # Log activity for cross-task visibility: executed code in sandbox - only explicit file path blocks, stripped file marker, typo corrected, parent dirs created
        summary_text = f'Executed message {message.id}{" block "+str(requested_block_idx) if requested_block_idx is not None else ""} in sandbox {sandbox.name if sandbox else "mock"} - {len(results)} file(s) -> {", ".join([r["remote_path"] for r in results])} (explicit file path blocks only, stripped # File: line, typo worksapce->workspace corrected, mkdir -p parent dirs, new files created if not exist)'
        detail_text = f"""Message {message.id} from {message.agent.name if message.agent else 'user'}: {message.content[:200]}

Code blocks total parsed: {len(all_parsed_blocks)}, explicit file path blocks (with # File: /workspace/...): {len(code_blocks)}
Blocks to execute: {len(blocks_to_execute)} (requested_block_idx={requested_block_idx})
Results: {results}

File marker stripping: # File: /workspace/... line removed from code before display and before write (per user: should not be part of code)
Typo correction: /worksapce/, /worspace/, /workpace/, /workpsace/ -> /workspace/ (user reported misspell)
Parent dirs: ensured via mkdir -p before write_text_to_sandbox (fixes fallback generic path parent missing)
Trying feedback: logged trying to create file, showing creating file in UI via button text 🧠 Executing... and task-exec-output panel

Full prompt snippet: {message.full_prompt[:2000] if message.full_prompt else 'none'}
"""
        activity = ProjectActivity(
            project_id=project.id,
            task_id=task.id,
            agent_id=message.agent_id,
            user_id=current_user.id,
            type='code_executed',
            summary=summary_text,
            detail=detail_text
        )
        db.session.add(activity)
        db.session.commit()

        # Request log as code per user request - shows trying and creating file, with stripping and typo correction
        request_log = f"""# REQUEST LOG - Execute Chat Message in Sandbox - per explicit file path block
# Message ID: {message_id} Task: {task.title} (ID {task.id}) - Executed block {requested_block_idx if requested_block_idx is not None else 'all explicit'}
# Project: {team.slug}/{project.slug} Sandbox: {sandbox.name if sandbox else 'mock'} (ID {sandbox_id})
# From: {current_user.username}
# Code blocks total: {len(all_parsed_blocks)}, explicit file path blocks (with # File: /workspace/...): {len(code_blocks)}, to execute: {len(blocks_to_execute)}
# Stripping: # File: line removed from code before write (per user: should not be part of code)
# Typo correction: worksapce, worspace, workpace, workpsace -> workspace
# Parent dirs: mkdir -p $(dirname remote_path) before write_text

from app.services.modal_sandbox_service import write_text_to_sandbox
import os

for idx, block in {blocks_to_execute}:
    # block is dict with code and text_before, explicit file path detection already done
    # remote_path is explicit like /workspace/contact.html (corrected typo if needed)
    # code_clean is code with # File: line stripped
    code = block['code'] if isinstance(block, dict) else block
    # Strip file marker line
    import re
    code_clean = re.sub(r'^#\\s*(?:File|Path):\\s*/workspace/[^\\n]*\\n', '', code, count=1, flags=re.MULTILINE)
    code_clean = re.sub(r'^<!--\\s*File:\\s*/workspace/[^\\n]*-->\\s*\\n', '', code_clean, count=1, flags=re.MULTILINE)
    code_clean = code_clean.lstrip()
    remote_path = "{results[0]['remote_path'] if results else '/workspace/...'}"
    # Correct typo
    remote_path = remote_path.replace('/worksapce/', '/workspace/').replace('/worspace/', '/workspace/')

    print(f"🧠 Trying to create file {{remote_path}} in sandbox {{sandbox_id}} - {{len(code_clean)}} chars - new file if not exists")
    # Ensure parent dir
    # await sb.exec.aio("bash", "-c", f"mkdir -p $(dirname {{remote_path}})")
    result = write_text_to_sandbox("{sandbox_id}", code_clean, remote_path)
    print(f"✅ Created {{remote_path}} - wrote {{len(code_clean)}} chars - file exists now at tunnel {{sandbox.tunnel_url}}/{'{remote_path.lstrip(\"/workspace/\")}' if 'remote_path' in locals() else ''}")

print(f"Executed message {message_id} - {len(results)} files written to sandbox /workspace - new files created if not exist, file marker stripped, typo corrected")
"""

        print(request_log)
        logger.info(f"Executed message {message_id} in sandbox {sandbox_id}: {len(results)} files - explicit file path blocks only, stripped file marker, typo corrected, parent dirs mkdir -p")

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({
                "success": True,
                "message_id": message_id,
                "sandbox_id": sandbox_id,
                "files_written": results,
                "request_log": request_log,
                "block_idx": requested_block_idx,
                "total_blocks": len(all_parsed_blocks),
                "explicit_blocks": len(code_blocks),
                "message": f"Executed message {message_id}{' block '+str(requested_block_idx) if requested_block_idx is not None else ''} - wrote {len(results)} files to /workspace in sandbox {sandbox.name if sandbox else 'mock'} - new files created if not exist, file marker stripped, typo worksapce->workspace corrected, trying feedback shown",
                "tunnel_url": sandbox.tunnel_url if sandbox else None,
                "file_urls": [f"{sandbox.tunnel_url}/{r['remote_path'].lstrip('/workspace/')}" if sandbox and sandbox.tunnel_url else r['remote_path'] for r in results] if results else []
            })

        flash(f'✅ Executed message {message_id}{" block "+str(requested_block_idx) if requested_block_idx is not None else ""} in sandbox - wrote {len(results)} file(s) to /workspace: {", ".join([r["remote_path"] for r in results])} - {"mock" if results and results[0].get("mock") else "real sandbox"} - stripped # File: line, corrected typo, mkdir -p', 'success')
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))

    except Exception as e:
        logger.exception(f"Execute message {message_id} in sandbox failed: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({"error": str(e), "message_id": message_id}), 500
        flash(f'❌ Execute failed: {e} - logged', 'danger')
        return redirect(url_for('tasks.view', team_slug=team.slug, project_slug=project.slug, task_id=task.id))
