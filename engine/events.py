"""Credit card event types — all 40 injectable + key derived events as dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AccountStatus(Enum):
    ACTIVE = "active"
    DEFAULT = "default"
    ACCELERATED = "accelerated"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class DisputeStatus(Enum):
    FILED = "filed"
    UNDER_INVESTIGATION = "under_investigation"
    RESOLVED_IN_FAVOR = "resolved_in_favor"
    RESOLVED_AGAINST = "resolved_against"
    REJECTED_ORAL_ONLY = "rejected_oral_only"
    CARDHOLDER_REJECTED_RESOLUTION = "cardholder_rejected_resolution"
    CU_FAILED_PROCEDURE = "cu_failed_procedure"


class DefaultCode(Enum):
    D1 = "missed_payment"
    D2 = "breach_of_any_cu_agreement"
    D3 = "bankruptcy_filed"
    D4 = "garnishment_of_cu_funds"
    D5 = "false_application_info"
    D6 = "repayment_ability_endangered"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """Base event. All events have a day number (1-based)."""
    day: int

    @property
    def priority(self) -> int:
        """Same-day ordering priority. Lower = processed first."""
        return _PRIORITY.get(type(self).__name__, 50)


# Same-day execution order (from our spec)
_PRIORITY = {
    # Calendar
    "BusinessDay": 0,
    # Transactions
    "Purchase": 10,
    "CashAdvanceATM": 10,
    "CashAdvanceOther": 10,
    "BalanceTransfer": 10,
    "ConvenienceCheckUsed": 10,
    "IllegalTransaction": 10,
    "MerchantCredit": 10,
    # Payments
    "PaymentReceived": 20,
    "PaymentReturned": 20,
    # Fees (injected, like card replacement request)
    "CardIssued": 25,
    "DocumentCopyRequested": 25,
    "ConvenienceCheckCopyRequested": 25,
    "ConvenienceCheckStopRequested": 25,
    # Daily snapshot
    "DailyBalanceSnapshot": 30,
    # Cycle end
    "CycleEnd": 40,
    # Defaults
    "DefaultTriggered": 60,
    # Disputes
    "BillingErrorClaimed": 70,
    "DisputeAcknowledged": 70,
    "DisputeResolvedInFavor": 70,
    "DisputeResolvedAgainst": 70,
    "CardholderRejectsResolution": 70,
    "PurchaseDisputeFiled": 70,
    # Unauthorized
    "UnauthorizedUse": 75,
    "UnauthorizedUseReported": 75,
    "GrossNegligenceFlagged": 75,
    # Admin / lifecycle
    "AccountOpened": 1,
    "AuthorizedUserAdded": 5,
    "AuthorizedUserRevoked": 5,
    "JointApplicantWithdrawal": 5,
    "CreditLimitChanged": 5,
    "AccountTerminatedByCU": 5,
    "AccountTerminatedByCardholder": 5,
    "SkipPaymentOffered": 5,
    "AccountSuspended": 5,
    "TermsChanged": 5,
    "AddressChanged": 5,
    "CreditInsurancePurchased": 5,
}


# ---------------------------------------------------------------------------
# Account Lifecycle (AL-01 through AL-11)
# ---------------------------------------------------------------------------

@dataclass
class AccountOpened(Event):
    cardholder_name: str = ""
    credit_limit: Decimal = Decimal("5000")
    apr_purchase: Decimal = Decimal("10.9")
    apr_cash_advance: Decimal = Decimal("12.9")
    card_product: Literal["platinum", "share_secured"] = "platinum"
    is_joint: bool = False
    joint_applicant_name: str = ""
    home_state: str = "TX"
    home_address: str = ""


@dataclass
class AuthorizedUserAdded(Event):
    user_name: str = ""


@dataclass
class AuthorizedUserRevoked(Event):
    user_name: str = ""
    card_returned: bool = False
    written_notice: bool = False


@dataclass
class JointApplicantWithdrawal(Event):
    applicant_name: str = ""
    written_notice: bool = False


@dataclass
class CreditLimitChanged(Event):
    new_limit: Decimal = Decimal("0")


@dataclass
class AccountTerminatedByCU(Event):
    notice_given: bool = True


@dataclass
class AccountTerminatedByCardholder(Event):
    written_notice: bool = True


@dataclass
class CardIssued(Event):
    recipient: str = "primary"
    is_replacement: bool = False


@dataclass
class SkipPaymentOffered(Event):
    cycle_to_skip: int = 0


@dataclass
class AccountSuspended(Event):
    reason: str = ""


# ---------------------------------------------------------------------------
# Transactions (TX-01 through TX-08)
# ---------------------------------------------------------------------------

@dataclass
class Purchase(Event):
    amount: Decimal = Decimal("0")
    merchant_name: str = ""
    merchant_state: str = ""
    distance_from_home_miles: float = 0.0
    by_user: str = "primary"
    is_international: bool = False
    via_advertisement: bool = False
    cu_owns_merchant: bool = False


@dataclass
class CashAdvanceATM(Event):
    amount: Decimal = Decimal("0")
    by_user: str = "primary"
    atm_operator_fee: Decimal = Decimal("0")
    is_international: bool = False


@dataclass
class CashAdvanceOther(Event):
    amount: Decimal = Decimal("0")
    by_user: str = "primary"
    is_international: bool = False


@dataclass
class BalanceTransfer(Event):
    amount: Decimal = Decimal("0")
    from_institution: str = ""


@dataclass
class ConvenienceCheckUsed(Event):
    amount: Decimal = Decimal("0")
    payee: str = ""


@dataclass
class IllegalTransaction(Event):
    amount: Decimal = Decimal("0")
    by_user: str = "primary"


@dataclass
class MerchantCredit(Event):
    amount: Decimal = Decimal("0")
    original_tx_day: int = 0


# ---------------------------------------------------------------------------
# Payments (PY-01 through PY-02)
# ---------------------------------------------------------------------------

@dataclass
class PaymentReceived(Event):
    amount: Decimal = Decimal("0")
    method: Literal["mail", "standard", "expedited"] = "standard"
    at_designated_address: bool = True


@dataclass
class PaymentReturned(Event):
    original_payment_day: int = 0
    amount: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Billing Cycle (injected trigger — engine derives the rest)
# ---------------------------------------------------------------------------

@dataclass
class CycleEnd(Event):
    """Injected to mark end of a billing cycle. Engine computes statement."""
    cycle_number: int = 0


# ---------------------------------------------------------------------------
# Disputes (DS-01 through DS-08)
# ---------------------------------------------------------------------------

@dataclass
class BillingErrorClaimed(Event):
    error_on_statement_day: int = 0
    amount: Decimal = Decimal("0")
    description: str = ""
    method: Literal["written", "oral"] = "written"


@dataclass
class DisputeAcknowledged(Event):
    dispute_id: int = 0


@dataclass
class DisputeResolvedInFavor(Event):
    dispute_id: int = 0


@dataclass
class DisputeResolvedAgainst(Event):
    dispute_id: int = 0
    amount_owed: Decimal = Decimal("0")


@dataclass
class CardholderRejectsResolution(Event):
    dispute_id: int = 0


@dataclass
class PurchaseDisputeFiled(Event):
    original_tx_day: int = 0
    amount: Decimal = Decimal("0")
    merchant_in_home_state: bool = False
    distance_from_home_miles: float = 0.0
    purchase_amount: Decimal = Decimal("0")
    paid_in_full: bool = False
    good_faith_attempt: bool = False
    via_cu_advertisement: bool = False
    cu_owns_merchant: bool = False
    used_card_directly: bool = True


# ---------------------------------------------------------------------------
# Unauthorized Use (UA-01 through UA-04)
# ---------------------------------------------------------------------------

@dataclass
class UnauthorizedUse(Event):
    amount: Decimal = Decimal("0")
    tx_type: Literal["purchase", "atm_cash", "other"] = "purchase"
    by_whom: str = "unknown"


@dataclass
class UnauthorizedUseReported(Event):
    method: Literal["oral", "written"] = "oral"


@dataclass
class GrossNegligenceFlagged(Event):
    description: str = ""


# ---------------------------------------------------------------------------
# Administrative (AD-01 through AD-08)
# ---------------------------------------------------------------------------

@dataclass
class TermsChanged(Event):
    notice_given: bool = True
    changes: dict = field(default_factory=dict)


@dataclass
class AddressChanged(Event):
    new_address: str = ""
    new_state: str = ""


@dataclass
class CreditInsurancePurchased(Event):
    premium_amount: Decimal = Decimal("0")


@dataclass
class DocumentCopyRequested(Event):
    doc_type: Literal["sales_draft", "statement"] = "sales_draft"
    is_cu_error_context: bool = False


@dataclass
class ConvenienceCheckCopyRequested(Event):
    pass


@dataclass
class ConvenienceCheckStopRequested(Event):
    check_id: str = ""


# ---------------------------------------------------------------------------
# Default / Enforcement (DF-01 through DF-09) — mostly derived
# ---------------------------------------------------------------------------

@dataclass
class CardholderBankruptcyFiled(Event):
    case_number: str = ""


@dataclass
class LegalGarnishmentAttempted(Event):
    by_whom: str = ""


@dataclass
class FalseInfoDiscovered(Event):
    what_was_false: str = ""


@dataclass
class RepaymentAbilityEndangered(Event):
    reason: str = ""


@dataclass
class CardSurrenderDemanded(Event):
    pass


@dataclass
class SecurityInterestEnforced(Event):
    accounts_offset: list = field(default_factory=list)
    amounts: list = field(default_factory=list)


@dataclass
class CollectionInitiated(Event):
    attorney_fees: Decimal = Decimal("0")
    court_costs: Decimal = Decimal("0")
    recovery_costs: Decimal = Decimal("0")
