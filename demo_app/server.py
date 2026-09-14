"""Intentionally hostile legacy credit-union console.

Design goals for the take-home:
- Multi-step flow: search → detail → form → review → irreversible confirm.
- Runtime exceptions: not-found, restricted member, validation, interstitial, timeout, slowness.
- Hostile markup: nested tables, iframe, generated IDs, no test IDs.
- Tenant branding switch so one artifact can be specialized rather than re-recorded.
- Human-readable labels remain, so accessibility/semantic locators still work.
"""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from demo_app.data import lookup_member, next_account_id

DEFAULT_HOST = os.environ.get("CUAS_DEMO_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("CUAS_DEMO_PORT", "8765"))

BRANDS: dict[str, dict[str, str]] = {
    "default": {
        "institution": "Summit Valley Credit Union",
        "product": "CU*CORE Teller Services — Region 4",
        "member_id_label": "Member ID",
        "search_button": "Search",
        "open_button": "Open New Sub-account",
        "confirm_button": "Confirm Open Account",
    },
    "eastside": {
        "institution": "Eastside Community CU",
        "product": "MemberServ Desktop (web)",
        "member_id_label": "Member Number",
        "search_button": "Find Member",
        "open_button": "Open Sub Account",
        "confirm_button": "Confirm Open Account",
    },
}


@dataclass
class Session:
    token: str
    created_at: float = field(default_factory=time.time)
    brand: str = "default"
    simulate: str | None = None
    notice_pending: bool = False
    expired: bool = False
    last_member_id: str | None = None
    pending_open: dict[str, Any] | None = None
    created_accounts: list[dict[str, Any]] = field(default_factory=list)


SESSIONS: dict[str, Session] = {}
CONFIRM_SEQ = 1000

app = FastAPI(title="CU*CORE Teller Services", docs_url=None, redoc_url=None)


def _uid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(3)}"


def _brand(session: Session) -> dict[str, str]:
    return BRANDS.get(session.brand, BRANDS["default"])


def _shell(title: str, body: str, *, session: Session, extra_css: str = "") -> str:
    brand = _brand(session)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ background:#d4d0c8; color:#000; font-family: Tahoma, "MS Sans Serif", sans-serif; font-size:12px; margin:0; }}
    .banner {{ background:#000080; color:#fff; padding:4px 8px; font-weight:bold; }}
    .sub {{ background:#c0c0c0; border-bottom:2px solid #808080; padding:3px 8px; }}
    .panel {{ background:#c0c0c0; border:2px solid; border-color:#fff #808080 #808080 #fff; margin:12px; padding:8px; }}
    table.layout {{ width:100%; border-collapse:collapse; }}
    table.grid {{ border-collapse:collapse; background:#fff; }}
    table.grid td, table.grid th {{ border:1px solid #808080; padding:4px 8px; font-size:12px; }}
    table.grid th {{ background:#000080; color:#fff; text-align:left; }}
    input, select {{ font-family: Tahoma, sans-serif; font-size:12px; }}
    button, input[type=submit] {{ background:#d4d0c8; border:2px solid; border-color:#fff #808080 #808080 #fff; padding:2px 12px; font-size:12px; }}
    .error {{ color:#800000; font-weight:bold; }}
    .ok {{ color:#006400; font-weight:bold; }}
    iframe {{ width:100%; height:220px; border:2px inset #808080; background:#fff; }}
    {extra_css}
  </style>
</head>
<body>
  <div class="banner">{brand["product"]}</div>
  <div class="sub">{brand["institution"]} &nbsp;|&nbsp; operator: STAFF01 &nbsp;|&nbsp; env: UAT</div>
  {body}
</body>
</html>
"""


def _get_session(request: Request) -> Session:
    token = request.cookies.get("cu_session")
    session = SESSIONS.get(token) if token else None
    if session is None:
        session = Session(token=secrets.token_hex(8))
        SESSIONS[session.token] = session
    brand = request.query_params.get("brand")
    if brand in BRANDS:
        session.brand = brand
    simulate = request.query_params.get("simulate")
    if simulate:
        session.simulate = simulate
        if simulate == "interstitial":
            session.notice_pending = True
        if simulate == "timeout":
            session.expired = True
    return session


def _attach_cookie(response: HTMLResponse | RedirectResponse, session: Session) -> HTMLResponse | RedirectResponse:
    response.set_cookie("cu_session", session.token, httponly=False, samesite="lax")
    return response


def _maybe_slow(session: Session) -> None:
    if session.simulate == "slow":
        time.sleep(2.2)


def html(session: Session, title: str, body: str, status: int = 200) -> HTMLResponse:
    response = HTMLResponse(_shell(title, body, session=session), status_code=status)
    return _attach_cookie(response, session)  # type: ignore[return-value]


def _expired_page(session: Session) -> HTMLResponse:
    body = """
    <div class="panel">
      <table class="layout"><tr><td>
        <p class="error">Session expired</p>
        <p>Your teller session is no longer valid. Re-authenticate to continue.</p>
        <p><a href="/">Return to console</a></p>
      </td></tr></table>
    </div>
    """
    return html(session, "Session expired", body, status=401)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    session = _get_session(request)
    if session.expired:
        return _expired_page(session)
    _maybe_slow(session)
    qs = urlencode({k: v for k, v in request.query_params.items() if k != "simulate"})
    iframe_src = "/search-panel" + (f"?{qs}" if qs else "")
    body = f"""
    <div class="panel">
      <table class="layout">
        <tr><td><b>Member Search</b> — look up a member before servicing the account.</td></tr>
        <tr><td>
          <iframe name="work" src="{iframe_src}" title="Search workspace"></iframe>
        </td></tr>
      </table>
    </div>
    """
    return html(session, "Member Search", body)


@app.get("/search-panel", response_class=HTMLResponse)
def search_panel(request: Request) -> HTMLResponse:
    session = _get_session(request)
    brand = _brand(session)
    field_id = _uid("fld")
    decoy_id = _uid("gen")
    error = request.query_params.get("error")
    error_html = f'<tr><td class="error" colspan="2">{error}</td></tr>' if error else ""
    body = f"""
    <form method="get" action="/search" target="_top">
      <table class="layout">
        <tr>
          <td>
            <table class="layout">
              <tr>
                <td><label for="{field_id}">{brand["member_id_label"]}</label></td>
                <td>
                  <input id="{field_id}" name="member_id" type="text" size="16" autocomplete="off">
                  <input type="hidden" id="{decoy_id}" name="nonce" value="{_uid('n')}">
                </td>
              </tr>
              {error_html}
              <tr>
                <td></td>
                <td><input type="submit" value="{brand["search_button"]}"></td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </form>
    """
    return html(session, "Search workspace", body)


@app.get("/search", response_model=None)
def search(request: Request) -> HTMLResponse | RedirectResponse:
    session = _get_session(request)
    if session.expired:
        return _expired_page(session)
    _maybe_slow(session)
    member_id = (request.query_params.get("member_id") or "").strip()
    member = lookup_member(member_id)
    if member is None:
        dest = "/not-found?member_id=" + member_id
        return _attach_cookie(RedirectResponse(dest, status_code=303), session)
    session.last_member_id = member_id
    dest = f"/members/{member_id}"
    if session.notice_pending:
        session.notice_pending = False
        dest = "/notice?next=" + dest
    return _attach_cookie(RedirectResponse(dest, status_code=303), session)


@app.get("/not-found", response_class=HTMLResponse)
def not_found(request: Request) -> HTMLResponse:
    session = _get_session(request)
    member_id = request.query_params.get("member_id", "")
    body = f"""
    <div class="panel">
      <p class="error">Member not found</p>
      <p>No record matches member id <b>{member_id}</b>.</p>
      <p><a href="/">Back to Member Search</a></p>
    </div>
    """
    return html(session, "Member not found", body)


@app.get("/notice", response_class=HTMLResponse)
def notice(request: Request) -> HTMLResponse:
    session = _get_session(request)
    nxt = request.query_params.get("next") or "/"
    body = f"""
    <div class="panel">
      <p><b>System Notice</b></p>
      <p>Overnight batch processing completed. Click Continue to resume teller operations.</p>
      <p><a href="{nxt}"><button type="button">Continue</button></a></p>
    </div>
    """
    return html(session, "System Notice", body)


@app.get("/members/{member_id}", response_class=HTMLResponse)
def member_detail(member_id: str, request: Request) -> HTMLResponse:
    session = _get_session(request)
    if session.expired:
        return _expired_page(session)
    _maybe_slow(session)
    member = lookup_member(member_id)
    if member is None:
        return not_found(request)
    brand = _brand(session)
    extra_accounts = [a for a in session.created_accounts if a.get("member_id") == member_id]
    rows = "\n".join(
        f"<tr><td>{a['id']}</td><td>{a['type']}</td><td>{a['nickname']}</td><td>{a['balance']}</td></tr>"
        for a in member["accounts"] + extra_accounts
    )
    savings = next(
        (a["balance"] for a in (member["accounts"] + extra_accounts) if a["type"] == "Savings"),
        "0.00",
    )
    action = (
        f'<a href="/members/{member_id}/forbidden"><button type="button">{brand["open_button"]}</button></a>'
        if member["status"] == "Restricted"
        else f'<a href="/members/{member_id}/subaccount/new"><button type="button">{brand["open_button"]}</button></a>'
    )
    body = f"""
    <div class="panel">
      <table class="layout">
        <tr><td>
          <table class="layout">
            <tr><td><b>Member detail</b></td><td align="right"><a href="/">New search</a></td></tr>
            <tr><td>Name</td><td>{member["name"]}</td></tr>
            <tr><td>Member ID</td><td>{member["member_id"]}</td></tr>
            <tr><td>Status</td><td>{member["status"]}</td></tr>
            <tr><td>Branch</td><td>{member["branch"]}</td></tr>
            <tr><td>Savings balance</td><td>{savings}</td></tr>
          </table>
        </td></tr>
        <tr><td>
          <table class="grid">
            <tr><th>Account</th><th>Type</th><th>Nickname</th><th>Balance</th></tr>
            {rows}
          </table>
        </td></tr>
        <tr><td>{action}</td></tr>
      </table>
    </div>
    """
    return html(session, f"Member {member_id}", body)


@app.get("/members/{member_id}/forbidden", response_class=HTMLResponse)
def forbidden(member_id: str, request: Request) -> HTMLResponse:
    session = _get_session(request)
    body = f"""
    <div class="panel">
      <p class="error">Permission denied</p>
      <p>This member is restricted. Sub-account origination is not allowed.</p>
      <p><a href="/members/{member_id}">Back to member</a></p>
    </div>
    """
    return html(session, "Permission denied", body)


@app.get("/members/{member_id}/subaccount/new", response_class=HTMLResponse)
def new_subaccount(member_id: str, request: Request) -> HTMLResponse:
    session = _get_session(request)
    if session.expired:
        return _expired_page(session)
    member = lookup_member(member_id)
    if member is None:
        return not_found(request)
    if member["status"] == "Restricted":
        return forbidden(member_id, request)
    error = request.query_params.get("error", "")
    error_html = f'<tr><td class="error" colspan="2">{error}</td></tr>' if error else ""
    nick_id = _uid("nick")
    dep_id = _uid("dep")
    body = f"""
    <div class="panel">
      <p><b>Open New Sub-account</b> for {member["name"]}</p>
      <form method="post" action="/members/{member_id}/subaccount/review">
        <table class="layout">
          <tr>
            <td><label for="acct_type">Account type</label></td>
            <td>
              <select id="acct_type" name="account_type">
                <option>Savings</option>
                <option>Money Market</option>
              </select>
            </td>
          </tr>
          <tr>
            <td>Nickname</td>
            <td><input id="{nick_id}" name="nickname" type="text" size="24" placeholder="Nickname"></td>
          </tr>
          <tr>
            <td>Initial deposit</td>
            <td><input id="{dep_id}" name="initial_deposit" type="text" size="10" placeholder="0.00"></td>
          </tr>
          {error_html}
          <tr><td></td><td><input type="submit" value="Review"></td></tr>
        </table>
      </form>
    </div>
    """
    return html(session, "Open New Sub-account", body)


@app.post("/members/{member_id}/subaccount/review", response_model=None)
async def review_subaccount(member_id: str, request: Request) -> HTMLResponse | RedirectResponse:
    session = _get_session(request)
    if session.expired:
        return _expired_page(session)
    form = await request.form()
    account_type = str(form.get("account_type") or "Savings")
    nickname = str(form.get("nickname") or "").strip()
    deposit_raw = str(form.get("initial_deposit") or "").strip()
    error = None
    if not nickname:
        error = "Nickname is required."
    try:
        deposit = float(deposit_raw)
        if deposit < 0:
            error = "Initial deposit must be greater than or equal to 0."
    except ValueError:
        deposit = 0.0
        error = "Initial deposit must be a number."
    if error:
        qs = urlencode({"error": error})
        return _attach_cookie(
            RedirectResponse(f"/members/{member_id}/subaccount/new?{qs}", status_code=303),
            session,
        )
    session.pending_open = {
        "member_id": member_id,
        "account_type": account_type,
        "nickname": nickname,
        "initial_deposit": f"{deposit:.2f}",
    }
    brand = _brand(session)
    pending = session.pending_open
    body = f"""
    <div class="panel">
      <p><b>Review sub-account</b></p>
      <table class="grid">
        <tr><th>Field</th><th>Value</th></tr>
        <tr><td>Member ID</td><td>{member_id}</td></tr>
        <tr><td>Account type</td><td>{pending["account_type"]}</td></tr>
        <tr><td>Nickname</td><td>{pending["nickname"]}</td></tr>
        <tr><td>Initial deposit</td><td>{pending["initial_deposit"]}</td></tr>
      </table>
      <p>This action creates a new share account and cannot be undone from this screen.</p>
      <form method="post" action="/members/{member_id}/subaccount/confirm">
        <input type="submit" value="{brand["confirm_button"]}">
      </form>
    </div>
    """
    return html(session, "Review sub-account", body)


@app.post("/members/{member_id}/subaccount/confirm", response_class=HTMLResponse)
async def confirm_subaccount(member_id: str, request: Request) -> HTMLResponse:
    global CONFIRM_SEQ
    session = _get_session(request)
    if session.expired:
        return _expired_page(session)
    pending = session.pending_open
    if not pending or pending.get("member_id") != member_id:
        body = """
        <div class="panel">
          <p class="error">Nothing to confirm</p>
          <p>The origination session is missing. Start again from member search.</p>
        </div>
        """
        return html(session, "Nothing to confirm", body, status=400)
    CONFIRM_SEQ += 1
    confirmation_id = f"CNF-2026-{CONFIRM_SEQ:05d}"
    account_id = next_account_id(pending["account_type"])
    session.created_accounts.append(
        {
            "member_id": member_id,
            "id": account_id,
            "type": pending["account_type"],
            "nickname": pending["nickname"],
            "balance": pending["initial_deposit"],
        }
    )
    session.pending_open = None
    body = f"""
    <div class="panel">
      <p class="ok">Account successfully created</p>
      <table class="grid">
        <tr><th>Field</th><th>Value</th></tr>
        <tr><td>Confirmation ID</td><td>{confirmation_id}</td></tr>
        <tr><td>New account</td><td>{account_id}</td></tr>
        <tr><td>Member ID</td><td>{member_id}</td></tr>
        <tr><td>Nickname</td><td>{session.created_accounts[-1]["nickname"]}</td></tr>
        <tr><td>Initial deposit</td><td>{session.created_accounts[-1]["balance"]}</td></tr>
      </table>
      <p><a href="/members/{member_id}">Back to member</a></p>
    </div>
    """
    return html(session, "Account successfully created", body)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


def create_app() -> FastAPI:
    return app
