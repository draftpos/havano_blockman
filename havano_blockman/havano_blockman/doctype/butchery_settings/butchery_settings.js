frappe.ui.form.on("Butchery Settings", {
    refresh: function(frm) {
        frm.set_query("weight_loss_account", function() {
            return {
                filters: {
                    "root_type": "Expense",
                    "is_group": 0
                }
            };
        });
    }
});
