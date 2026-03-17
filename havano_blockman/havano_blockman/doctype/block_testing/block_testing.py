import frappe
import json
from frappe.model.document import Document

class BlockTesting(Document):

    def before_save(self):
        total_cut = sum(row.cut_weight or 0 for row in self.items)
        if self.full_cut:
            self.weight_loss = (self.carcus_weight or 0) - total_cut
        else:
            self.weight_loss = (self.carcass_cut_weight or 0) - total_cut

    def validate(self):
        if not self.full_cut and not self.carcass_cut_weight:
            frappe.throw("Carcass Cut Weight is required for partial cuts.")
        total_cut = sum(row.cut_weight or 0 for row in self.items)
        active_weight = self.carcus_weight if self.full_cut else self.carcass_cut_weight
        if total_cut > (active_weight or 0):
            frappe.throw("Total cut weight ({0}) cannot exceed carcass cut weight ({1}).".format(total_cut, active_weight))

    def on_submit(self):
        self._create_stock_entries()

    def on_cancel(self):
        self._cancel_stock_entries()

    def _get_warehouse(self):
        warehouse = frappe.db.sql("""
            SELECT pii.warehouse
            FROM `tabPurchase Invoice Item` pii
            JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
            WHERE pi.custom_batch_number_ = %s
            AND pii.item_code = %s
            AND pi.docstatus != 2
            LIMIT 1
        """, (self.batch_number, self.carcus), as_dict=True)

        if warehouse and warehouse[0].warehouse:
            return warehouse[0].warehouse
        return "Stores - CD"

    def _get_valuation_rate(self, item_code):
        return frappe.db.get_value("Item", item_code, "valuation_rate") or 0

    def _create_stock_entries(self):
        warehouse = self._get_warehouse()
        settings = frappe.get_single("Butchery Settings")

        # Use carcass_cut_weight for partial, carcus_weight for full
        issue_qty = self.carcus_weight if self.full_cut else self.carcass_cut_weight

        # 1. Material Issue — carcass going OUT
        issue = frappe.new_doc("Stock Entry")
        issue.stock_entry_type = "Material Issue"
        issue.posting_date = self.date
        issue.company = self.company
        issue.custom_block_testing = self.name
        issue.append("items", {
            "item_code": self.carcus,
            "qty": issue_qty,
            "s_warehouse": warehouse,
            "basic_rate": self._get_valuation_rate(self.carcus),
            "allow_zero_valuation_rate": 1
        })
        issue.insert(ignore_permissions=True)
        issue.submit()

        # 2. Material Receipt — cut items coming IN
        receipt = frappe.new_doc("Stock Entry")
        receipt.stock_entry_type = "Material Receipt"
        receipt.posting_date = self.date
        receipt.company = self.company
        receipt.custom_block_testing = self.name
        for row in self.items:
            if not row.item_code or not row.cut_weight:
                continue
            receipt.append("items", {
                "item_code": row.item_code,
                "qty": row.cut_weight,
                "t_warehouse": warehouse,
                "basic_rate": self._get_valuation_rate(row.item_code),
                "allow_zero_valuation_rate": 1
            })
        receipt.insert(ignore_permissions=True)
        receipt.submit()

        # 3. Weight loss journal entry
        weight_loss = self.weight_loss or 0
        if weight_loss > 0 and settings.weight_loss_account:
            valuation_rate = self._get_valuation_rate(self.carcus)
            loss_amount = weight_loss * valuation_rate

            if loss_amount > 0:
                je = frappe.new_doc("Journal Entry")
                je.posting_date = self.date
                je.company = self.company
                je.custom_block_testing = self.name
                je.append("accounts", {
                    "account": settings.weight_loss_account,
                    "debit_in_account_currency": loss_amount
                })
                stock_account = frappe.db.get_value("Account",
                    {"account_type": "Stock Adjustment", "company": self.company, "is_group": 0}, "name")
                if stock_account:
                    je.append("accounts", {
                        "account": stock_account,
                        "credit_in_account_currency": loss_amount
                    })
                je.insert(ignore_permissions=True)
                je.submit()

        frappe.db.commit()

    def _cancel_stock_entries(self):
        for doctype in ["Stock Entry", "Journal Entry"]:
            linked = frappe.get_all(doctype,
                filters={"custom_block_testing": self.name, "docstatus": 1})
            for d in linked:
                doc = frappe.get_doc(doctype, d.name)
                doc.cancel()
        frappe.db.commit()


@frappe.whitelist()
def get_carcass_weight(batch_number, item_codes):
    result = frappe.db.sql("""
        SELECT SUM(pii.qty) as total
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.custom_batch_number_ = %s
        AND pii.item_code = %s
        AND pi.docstatus != 2
    """, (batch_number, item_codes), as_dict=True)

    return result[0].total or 0 if result else 0


@frappe.whitelist()
def get_remaining_carcass_weight(batch_number, carcus, current_doc=None):
    # Get original qty from Purchase Invoice
    result = frappe.db.sql("""
        SELECT SUM(pii.qty) as total
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.custom_batch_number_ = %s
        AND pii.item_code = %s
        AND pi.docstatus != 2
    """, (batch_number, carcus), as_dict=True)

    original_qty = result[0].total or 0 if result else 0

    # Sum carcass_cut_weight from previous partial entries
    # and carcus_weight from previous full entries
    filters = {
        "carcus": carcus,
        "batch_number": batch_number,
        "docstatus": 1
    }
    if current_doc:
        filters["name"] = ["!=", current_doc]

    previous = frappe.db.get_all("Block Testing",
        filters=filters,
        fields=["full_cut", "carcus_weight", "carcass_cut_weight"]
    )

    used = sum(
        (p.carcus_weight or 0) if p.full_cut else (p.carcass_cut_weight or 0)
        for p in previous
    )
    remaining = original_qty - used

    return {
        "remaining": remaining if remaining > 0 else 0,
        "original": original_qty,
        "used": used
    }