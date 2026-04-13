"""FastAPI web application for the Credit Card Agreement Simulation Engine."""

from __future__ import annotations

import json
import os
import uuid
import shutil
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
# Load .env from project root (not web/ dir)
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

app = FastAPI(title="Credit Card Agreement Engine")

DATA_DIR = Path(__file__).parent / "data"
STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR.mkdir(exist_ok=True)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        return super().default(obj)


def _serialize(obj) -> dict:
    """Convert engine objects to JSON-serializable dicts."""
    return json.loads(json.dumps(obj, cls=DecimalEncoder, default=str))


# ===================================================================
# Serve the frontend
# ===================================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ===================================================================
# Contract Instance API
# ===================================================================

@app.get("/api/contracts")
async def list_contracts():
    """List all saved contract instances."""
    instances = []
    for d in sorted(DATA_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["id"] = d.name
            instances.append(meta)
    return instances


@app.post("/api/contracts")
async def create_contract(file: UploadFile = File(...)):
    """Upload a contract .md, parse via LLM, save as instance."""
    instance_id = str(uuid.uuid4())[:8]
    instance_dir = DATA_DIR / instance_id
    instance_dir.mkdir(parents=True)

    # Save the uploaded contract
    content = await file.read()
    contract_path = instance_dir / "contract.md"
    contract_path.write_bytes(content)

    # Parse via LLM
    from engine.parser import parse_contract
    try:
        ir = parse_contract(str(contract_path))
    except Exception as e:
        shutil.rmtree(instance_dir)
        raise HTTPException(status_code=500, detail=f"Failed to parse contract: {e}")

    # Save IR
    ir_path = instance_dir / "ir.json"
    ir_path.write_text(json.dumps(ir, indent=2, cls=DecimalEncoder))

    # Generate deterministic English
    from engine.decompiler import decompile_to_english
    english = decompile_to_english(ir)
    (instance_dir / "english.md").write_text(english)

    # Save metadata
    meta = {
        "id": instance_id,
        "filename": file.filename,
        "created": datetime.now().isoformat(),
        "issuer": ir.get("meta", {}).get("issuer_name", "Unknown"),
        "network": ir.get("meta", {}).get("network", ""),
        "governing_law": ir.get("meta", {}).get("governing_law_state", ""),
    }

    # Extract key terms for display
    interest = ir.get("interest", {})
    rates = interest.get("daily_periodic_rates", [])
    if rates:
        aprs = [r.get("apr", "?") for r in rates]
        meta["apr_range"] = f"{min(aprs)}%-{max(aprs)}%"
    else:
        meta["apr_range"] = "N/A"

    grace = ir.get("grace_period", {})
    meta["grace_days"] = grace.get("purchases_days", "N/A")

    mp = ir.get("minimum_payment", {})
    meta["min_payment"] = f"{mp.get('percent_of_balance', '?')}% or ${mp.get('floor_amount', '?')}"

    fees = ir.get("fees", {})
    lp = fees.get("late_payment", {})
    meta["late_fee"] = f"${lp.get('amount', '?')}" if isinstance(lp, dict) else f"${lp}"

    meta_path = instance_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    return meta


@app.post("/api/contracts/from-ir")
async def create_contract_from_ir(file: UploadFile = File(...)):
    """Upload an existing IR .json directly (no LLM needed)."""
    instance_id = str(uuid.uuid4())[:8]
    instance_dir = DATA_DIR / instance_id
    instance_dir.mkdir(parents=True)

    content = await file.read()
    ir = json.loads(content)

    ir_path = instance_dir / "ir.json"
    ir_path.write_text(json.dumps(ir, indent=2, cls=DecimalEncoder))

    from engine.decompiler import decompile_to_english
    english = decompile_to_english(ir)
    (instance_dir / "english.md").write_text(english)

    meta = {
        "id": instance_id,
        "filename": file.filename,
        "created": datetime.now().isoformat(),
        "issuer": ir.get("meta", {}).get("issuer_name", "Unknown"),
        "network": ir.get("meta", {}).get("network", ""),
        "governing_law": ir.get("meta", {}).get("governing_law_state", ""),
        "apr_range": "N/A",
        "grace_days": ir.get("grace_period", {}).get("purchases_days", "N/A"),
        "min_payment": "N/A",
        "late_fee": "N/A",
        "from_ir": True,
    }

    interest = ir.get("interest", {})
    rates = interest.get("daily_periodic_rates", [])
    if rates:
        aprs = [r.get("apr", "?") for r in rates]
        meta["apr_range"] = f"{min(aprs)}%-{max(aprs)}%"

    (instance_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


@app.get("/api/contracts/{instance_id}")
async def get_contract(instance_id: str):
    """Get full contract IR and metadata."""
    instance_dir = DATA_DIR / instance_id
    if not instance_dir.exists():
        raise HTTPException(status_code=404, detail="Contract not found")

    meta = json.loads((instance_dir / "meta.json").read_text())
    ir = json.loads((instance_dir / "ir.json").read_text())

    return {"meta": meta, "ir": ir}


@app.get("/api/contracts/{instance_id}/english")
async def get_english(instance_id: str):
    """Get deterministic English decompilation."""
    instance_dir = DATA_DIR / instance_id
    english_path = instance_dir / "english.md"
    if not english_path.exists():
        raise HTTPException(status_code=404)
    return {"english": english_path.read_text()}


@app.delete("/api/contracts/{instance_id}")
async def delete_contract(instance_id: str):
    instance_dir = DATA_DIR / instance_id
    if instance_dir.exists():
        shutil.rmtree(instance_dir)
    return {"deleted": instance_id}


# ===================================================================
# Analysis API
# ===================================================================

@app.post("/api/contracts/{instance_id}/analyze")
async def analyze_statements(instance_id: str, file: UploadFile = File(...)):
    """Upload statement HTML, run cycle analysis against the contract."""
    instance_dir = DATA_DIR / instance_id
    if not instance_dir.exists():
        raise HTTPException(status_code=404, detail="Contract not found")

    # Save uploaded statements
    analyses_dir = instance_dir / "analyses"
    analyses_dir.mkdir(exist_ok=True)

    analysis_id = str(uuid.uuid4())[:8]
    analysis_dir = analyses_dir / analysis_id
    analysis_dir.mkdir()

    content = await file.read()
    stmt_path = analysis_dir / "statements.html"
    stmt_path.write_bytes(content)

    # Load the contract IR for evidence linking
    ir = json.loads((instance_dir / "ir.json").read_text())

    # Run cycle engine
    from engine.statement_input import parse_statement_html
    from engine.cycle_engine import run_cycles

    history = parse_statement_html(str(stmt_path))
    results = run_cycles(history)

    # Serialize results
    cycles_data = []
    for i, r in enumerate(results):
        cd = history.cycles[i]
        cycle = {
            "cycle_number": r.cycle_number,
            "cycle_start": str(r.cycle_start),
            "cycle_end": str(r.cycle_end),
            "days_in_cycle": r.days_in_cycle,
            "summary": {
                "previous_balance": str(r.previous_balance),
                "purchases": str(r.total_purchases),
                "cash_advances": str(r.total_cash_advances),
                "fees": str(r.total_fees),
                "interest": str(r.total_interest),
                "payments": str(r.total_payments),
                "new_balance": str(r.new_balance),
                "minimum_payment": str(r.minimum_payment),
                "due_date": str(r.payment_due_date) if r.payment_due_date else None,
            },
            "transactions": [
                {
                    "date": str(tx.post_date),
                    "description": tx.description,
                    "category": tx.category,
                    "amount": str(tx.amount),
                }
                for tx in sorted(cd.transactions, key=lambda t: t.post_date)
            ],
            "interest_explanation": _serialize_interest(r),
            "grace_explanation": _serialize_grace(r),
            "fee_explanations": _serialize_fees(r),
            "payment_explanations": _serialize_payments(r),
        }
        cycles_data.append(cycle)

    result = {
        "analysis_id": analysis_id,
        "instance_id": instance_id,
        "cardholder": history.params.cardholder_name,
        "account": history.params.account_number,
        "credit_limit": str(history.params.credit_limit),
        "purchase_apr": str(history.params.purchase_apr),
        "cash_advance_apr": str(history.params.cash_advance_apr),
        "single_rate": history.params.single_rate,
        "rate_type": history.params.rate_type,
        "num_cycles": len(cycles_data),
        "cycles": cycles_data,
        "contract_evidence": _build_evidence(ir),
    }

    # Save
    (analysis_dir / "results.json").write_text(
        json.dumps(result, indent=2, cls=DecimalEncoder))

    return result


@app.get("/api/contracts/{instance_id}/analyses")
async def list_analyses(instance_id: str):
    """List all analyses for a contract instance."""
    analyses_dir = DATA_DIR / instance_id / "analyses"
    if not analyses_dir.exists():
        return []
    results = []
    for d in sorted(analyses_dir.iterdir()):
        rpath = d / "results.json"
        if rpath.exists():
            data = json.loads(rpath.read_text())
            results.append({
                "analysis_id": data["analysis_id"],
                "cardholder": data.get("cardholder", ""),
                "num_cycles": data.get("num_cycles", 0),
            })
    return results


@app.get("/api/contracts/{instance_id}/analyses/{analysis_id}")
async def get_analysis(instance_id: str, analysis_id: str):
    """Get full analysis results."""
    rpath = DATA_DIR / instance_id / "analyses" / analysis_id / "results.json"
    if not rpath.exists():
        raise HTTPException(status_code=404)
    return json.loads(rpath.read_text())


# ===================================================================
# Serializers
# ===================================================================

def _serialize_interest(r):
    ie = r.interest_explanation
    if not ie:
        return None
    grace = r.grace_explanation and r.grace_explanation.eligible

    entries = []
    for e in (ie.adb_entries or []):
        entries.append({
            "start": e.start_date.strftime("%m/%d"),
            "end": e.end_date.strftime("%m/%d"),
            "days": e.days,
            "balance": str(e.daily_balance),
            "subtotal": str(e.subtotal),
            "activity": e.activity,
        })

    return {
        "total": str(ie.total_interest),
        "purchase_interest": str(ie.purchase_interest),
        "cash_advance_interest": str(ie.cash_advance_interest),
        "purchase_adb": str(ie.purchase_adb),
        "cash_advance_adb": str(ie.cash_advance_adb),
        "purchase_rate": str(ie.purchase_rate),
        "purchase_apr": str(ie.purchase_apr),
        "cash_advance_rate": str(ie.cash_advance_rate),
        "cash_advance_apr": str(ie.cash_advance_apr),
        "days_in_cycle": ie.days_in_cycle,
        "grace_active": grace,
        "grace_note": ie.grace_note or "",
        "rate_type": getattr(ie, 'rate_type', 'daily'),
        "adb_entries": entries,
        "carried_balance": str(entries[0]["balance"]) if entries else "0.00",
    }


def _serialize_grace(r):
    ge = r.grace_explanation
    if not ge:
        return None
    return {
        "eligible": ge.eligible,
        "reason": ge.reason,
    }


def _serialize_fees(r):
    return [
        {
            "date": str(f.fee_date),
            "description": f.description,
            "amount": str(f.amount),
            "clause_ref": f.clause_ref,
            "justification": f.justification,
        }
        for f in r.fee_explanations
    ]


def _serialize_payments(r):
    result = []
    for pe in r.payment_explanations:
        result.append({
            "date": str(pe.payment_date),
            "amount": str(pe.total_amount),
            "minimum_required": str(pe.minimum_required),
            "excess": str(pe.excess_amount),
            "excess_applied_to": pe.excess_applied_to,
            "steps": [
                {
                    "component": s.component,
                    "amount": str(s.amount),
                    "applied_to": s.applied_to,
                }
                for s in pe.steps
            ],
        })
    return result


def _build_evidence(ir: dict) -> dict:
    """Extract contract clause text for evidence linking in the UI."""
    interest = ir.get("interest") or {}
    grace = ir.get("grace_period") or {}
    fees = ir.get("fees") or {}
    pa = ir.get("payment_application") or {}
    mp = ir.get("minimum_payment") or {}
    liab = ir.get("liability") or {}
    dt = ir.get("default_triggers") or []

    rates = interest.get("daily_periodic_rates") or []
    rate_text = "; ".join(
        f"{r.get('apr', '?')}% APR (periodic rate: {r.get('daily_rate', '?')})"
        for r in rates
    )

    fee_items = {}
    lp = fees.get("late_payment")
    if lp:
        fee_items["late_payment"] = {
            "amount": lp.get("amount") if isinstance(lp, dict) else lp,
            "clause": lp.get("source_clause", "Section 7") if isinstance(lp, dict) else "Section 7",
            "rule": "If you are late in making a payment, a late charge may be added to your account.",
        }
    rp = fees.get("returned_payment")
    if rp:
        fee_items["returned_payment"] = {
            "amount": rp.get("amount") if isinstance(rp, dict) else rp,
            "clause": rp.get("source_clause", "Section 7") if isinstance(rp, dict) else "Section 7",
            "rule": "If a payment is returned unpaid, a fee may be charged. Fee shall not exceed the minimum payment.",
        }
    ol = fees.get("over_limit")
    if ol and isinstance(ol, dict):
        fee_items["over_limit"] = {
            "amount": ol.get("amount"),
            "clause": ol.get("source_clause", "Section 7"),
            "rule": "A fee may be charged if the New Balance exceeds the credit limit on the statement date.",
        }

    waterfall = (pa.get("minimum_payment_order") or [])
    waterfall_text = " → ".join(
        s.replace("_", " ") for s in waterfall
    ) if waterfall else "N/A"

    return {
        "interest": {
            "clause": interest.get("source_clause", "Section 6"),
            "method": (interest.get("method") or "").replace("_", " "),
            "rates": rate_text,
            "rule": "The INTEREST CHARGE is figured by applying the periodic rate to the Average Daily Balance.",
        },
        "grace_period": {
            "clause": grace.get("source_clause", "Section 6"),
            "days": grace.get("purchases_days"),
            "condition": (grace.get("condition") or "").replace("_", " "),
            "rule": f"You have {grace.get('purchases_days', '?')} days to repay before interest on new purchases is imposed, if previous balance was paid in full. Cash advances have no grace period.",
        },
        "fees": fee_items,
        "payment_waterfall": {
            "clause": pa.get("source_clause", "Section 10"),
            "order": waterfall_text,
            "excess": (pa.get("excess_payment_order") or "highest rate first").replace("_", " "),
            "rule": f"Minimum payment applied: {waterfall_text}. Excess applied to highest-rate balance first.",
        },
        "minimum_payment": {
            "clause": mp.get("source_clause", "Section 5"),
            "formula": f"{mp.get('percent_of_balance', '?')}% of balance or ${mp.get('floor_amount', '?')}, whichever is greater",
            "threshold": mp.get("pay_in_full_threshold"),
        },
        "default_triggers": [
            {"code": d.get("code"), "condition": (d.get("condition") or "").replace("_", " ")}
            for d in dt
        ],
    }


# ===================================================================
# Run
# ===================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
