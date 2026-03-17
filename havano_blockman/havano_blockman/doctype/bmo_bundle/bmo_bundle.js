frappe.ui.form.on('BMO Bundle', {
    setup: function(frm) {
        // no filter - all items allowed
    }
});

frappe.ui.form.on('BMO Bundle Item', {
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (!row.item_code) return;
        frappe.db.get_value('Item', row.item_code, ['item_name', 'stock_uom'])
            .then(function(r) {
                frappe.model.set_value(cdt, cdn, 'item_name', r.message.item_name);
                frappe.model.set_value(cdt, cdn, 'uom', r.message.stock_uom);
            });
    }
});
