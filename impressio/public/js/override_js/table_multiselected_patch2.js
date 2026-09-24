// Wait for desk to load
$(document).on("app_ready", function () {
	console.log("🔧 Table MultiSelect Child-Table Stable Patch Loaded");

	// --- Safe remove function ---
	frappe.ui.form.ControlTableMultiSelect.prototype._remove_value = function (value) {
		const link_field = this.get_link_field();

		// Remove from internal rows
		this.rows = (this.rows || []).filter((row) => this.get_link_value(row) !== value);

		// Remove from frm child table if linked
		if (this.frm) {
			let table = this.frm.doc[this.df.fieldname] || [];
			table = table.filter((row) => row[link_field.fieldname] !== value);
			this.frm.doc[this.df.fieldname] = table;
		}

		// Track removed values to prevent re-adding
		this._removed_values = this._removed_values || [];
		if (!this._removed_values.includes(value)) this._removed_values.push(value);

		this.set_formatted_input(this.rows);
		this.parse_validate_and_set_in_model("");
	};

	// --- Override make_input ---
	const old_make_input = frappe.ui.form.ControlTableMultiSelect.prototype.make_input;
	frappe.ui.form.ControlTableMultiSelect.prototype.make_input = function () {
		old_make_input.call(this);

		this.$input_area.off("click", ".btn-remove");

		this.$input_area.on("click", ".btn-remove", (e) => {
			const $target = $(e.currentTarget);
			const $value = $target.closest(".tb-selected-value");
			const value = decodeURIComponent($value.data().value);

			this._remove_value(value);
		});

		this.$input.on("awesomplete-selectcomplete", () => {
			this.$input.val("").focus();
		});

		// Initialize removed values array
		this._removed_values = this._removed_values || [];
	};

	// --- Override parse to prevent overwriting saved rows ---
	const old_parse = frappe.ui.form.ControlTableMultiSelect.prototype.parse;
	frappe.ui.form.ControlTableMultiSelect.prototype.parse = function (value, label) {
		if (typeof value === "object") return value;

		const link_field = this.get_link_field();
		if (!link_field || !value) return this.rows || [];

		// Initialize rows and removed arrays
		this.rows = this.rows || (this.frm ? this.frm.doc[this.df.fieldname] || [] : []);
		this._removed_values = this._removed_values || [];

		// Do not add removed values
		if (this._removed_values.includes(value)) return this.rows;

		if (this.frm) {
			// Ensure child table exists
			if (!this.frm.doc[this.df.fieldname]) this.frm.doc[this.df.fieldname] = [];

			// Check if value already exists in child table
			const exists_in_table = this.frm.doc[this.df.fieldname].some(
				(row) => row[link_field.fieldname] === value
			);

			if (!exists_in_table) {
				// Add new child row
				const new_row = frappe.model.add_child(
					this.frm.doc,
					this.df.options,
					this.df.fieldname
				);
				new_row[link_field.fieldname] = value;

				// Merge into internal rows
				const exists_in_rows = this.rows.some(
					(row) => row[link_field.fieldname] === value
				);
				if (!exists_in_rows) this.rows.push(new_row);
			}
		} else {
			// Local rows (not linked to frm)
			const exists_in_rows = this.rows.some((row) => row[link_field.fieldname] === value);
			if (!exists_in_rows) this.rows.push({ [link_field.fieldname]: value });
		}

		frappe.utils.add_link_title(link_field.options, value, label);

		// Update internal rows list for awesomplete filtering
		this._rows_list = this.rows.map((row) => this.get_link_value(row));
		return this.rows;
	};

	// --- Helper to safely get value of a row ---
	frappe.ui.form.ControlTableMultiSelect.prototype.get_link_value = function (row) {
		const link_field = this.get_link_field();
		return row && link_field ? row[link_field.fieldname] : null;
	};

	// --- Override set_formatted_input to render pills ---
	frappe.ui.form.ControlTableMultiSelect.prototype.set_formatted_input = function (value) {
		this.rows = value || [];
		this._rows_list = (this.rows || []).map((row) => this.get_link_value(row));
		this.set_pill_html(this._rows_list);
	};

	// --- Override set_pill_html to safely render ---
	const old_set_pill_html = frappe.ui.form.ControlTableMultiSelect.prototype.set_pill_html;
	frappe.ui.form.ControlTableMultiSelect.prototype.set_pill_html = function (values) {
		const link_field = this.get_link_field();
		if (!link_field) return; // skip if meta not loaded

		const html = (values || []).map((value) => this.get_pill_html(value)).join("");
		this.$input_area.find(".tb-selected-value").remove();
		this.$input_area.prepend(html);
	};

	// --- Override custom_awesomplete_filter ---
	frappe.ui.form.ControlTableMultiSelect.prototype.custom_awesomplete_filter = function (
		awesomplete
	) {
		const me = this;
		awesomplete.filter = function (item) {
			return (
				!(me._rows_list || []).includes(item.value) &&
				!(me._removed_values || []).includes(item.value)
			);
		};
	};
});
