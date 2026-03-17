frappe.ui.form.on("Block Testing", {
    refresh: function(frm) {
        if (frm.doc.__islocal) {
            frm.set_value("carcus_weight", 0);
            frm.set_value("weight_loss", 0);
        }
        toggle_carcass_cut_weight(frm);
    },

    full_cut: function(frm) {
        toggle_carcass_cut_weight(frm);
        calculate_weight_loss(frm);
    },

    batch_number: function(frm) {
        if (frm.doc.batch_number && frm.doc.carcus) {
            fetch_carcass_weight_from_batch(frm);
        }
    },

    carcus: function(frm) {
        if (!frm.doc.carcus || frm.doc.docstatus !== 0 || frm.doc.items.length > 0) return;
        frappe.db.get_doc("BMO Bundle", frm.doc.carcus)
            .then(function(bundle) {
                frm.clear_table("items");
                let promises = bundle.items.map(function(row) {
                    return Promise.all([
                        frappe.db.get_value("Item", row.item_code, ["item_name", "standard_rate", "valuation_rate"]),
                        frappe.db.get_value("Bin", {"item_code": row.item_code}, ["actual_qty"])
                    ]).then(function(results) {
                        let item_data = results[0].message;
                        let bin_data = results[1].message;
                        let current = bin_data ? (bin_data.actual_qty || 0) : 0;
                        let child = frm.add_child("items");
                        child.item_code = row.item_code;
                        child.item_name = item_data.item_name || row.item_code;
                        child.rate = item_data.standard_rate || item_data.valuation_rate || 0;
                        child.current_weight = current;
                        child.cut_weight = 0;
                        child.new_weight = current;
                    });
                });
                Promise.all(promises).then(function() {
                    frm.refresh_field("items");
                    if (frm.doc.batch_number) {
                        fetch_carcass_weight_from_batch(frm);
                    }
                });
            });
    }
});

frappe.ui.form.on("Havano Bundle Item", {
    cut_weight: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        frappe.model.set_value(cdt, cdn, "new_weight",
            (row.current_weight || 0) + (row.cut_weight || 0)
        );
        calculate_weight_loss(frm);
    }
});

function toggle_carcass_cut_weight(frm) {
    frm.toggle_display("carcass_cut_weight", !frm.doc.full_cut);
    frm.toggle_reqd("carcass_cut_weight", !frm.doc.full_cut);
}

function calculate_weight_loss(frm) {
    let total_cut = 0;
    (frm.doc.items || []).forEach(function(r) {
        total_cut += r.cut_weight || 0;
    });
    let active_weight = frm.doc.full_cut
        ? (frm.doc.carcus_weight || 0)
        : (frm.doc.carcass_cut_weight || 0);
    let weight_loss = active_weight - total_cut;
    frm.set_value("weight_loss", weight_loss);
}

function fetch_carcass_weight_from_batch(frm) {
    if (!frm.doc.carcus || !frm.doc.batch_number) return;

    frappe.db.get_list("Block Testing", {
        filters: {
            carcus: frm.doc.carcus,
            batch_number: frm.doc.batch_number,
            full_cut: 1,
            docstatus: 1
        },
        fields: ["name"],
        limit: 1
    }).then(function(existing) {
        if (existing && existing.length > 0) {
            frm.set_value("carcus_weight", 0);
            frm.set_value("weight_loss", 0);
            frm.refresh_field("carcus_weight");
            frappe.msgprint({
                title: __("Full Cut Already Done"),
                message: __("A full cut has already been completed for this Carcass and Batch. Carcass weight is 0."),
                indicator: "orange"
            });
            return;
        }

        frappe.call({
            method: "havano_blockman.havano_blockman.doctype.block_testing.block_testing.get_remaining_carcass_weight",
            args: {
                batch_number: frm.doc.batch_number,
                carcus: frm.doc.carcus,
                current_doc: frm.doc.name || ""
            },
            callback: function(r) {
                if (r.message) {
                    let remaining = r.message.remaining;
                    let original = r.message.original;
                    let used = r.message.used;

                    frm.set_value("carcus_weight", remaining);
                    frm.refresh_field("carcus_weight");
                    calculate_weight_loss(frm);

                    if (used > 0) {
                        frappe.show_alert({
                            message: __("Remaining: {0} of {1} original. {2} already used.", [remaining, original, used]),
                            indicator: "blue"
                        }, 5);
                    }
                }
            }
        });
    });
}