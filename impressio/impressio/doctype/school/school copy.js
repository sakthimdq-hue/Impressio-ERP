// Copyright (c) 2025, MDQ
// ===============================
// SCHOOL FORM CONTROLLER (row_key version)
// ===============================

// ===============================
// UTILITY: Generate 10-character unique row_key
// ===============================
function generate_row_key(length = 10) {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let key = '';
    for (let i = 0; i < length; i++) {
        key += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return key;
}

// ===============================
// FORM EVENT
// ===============================

frappe.ui.form.on("School", {
    refresh(frm) {
        inject_costing_scroll_css();

        // Students tab
        const tabSelector = `
            .form-sidebar a[data-fieldname="students_tab"],
            .nav-link[data-fieldname="students_tab"]
        `;

        frm.is_new() ? $(tabSelector).hide() : $(tabSelector).show();

        // Lock tables
        // full_lock_child_grid(frm, "grades_details");
        // lock_child_grid(frm, "uniform_details");
        // lock_child_grid(frm, "books_details");

        // School code dropdown - only for new forms

        if (frm.is_new()) {
            setTimeout(() => {
                const field = frm.fields_dict.school_code;
                if (field && field.$input) {
                    field.$input.prop("readonly", true); // blocks typing
                }
            }, 100);
        } else {
            const field = frm.fields_dict.school_code;
            if (field && field.$input) {
                field.$input.prop("readonly", false);
            }
        }


        if (frm.is_new()) {
            set_school_code_dropdown(frm);
        }

        // Testing function
        // fetch_full_lead_data();


        // Sidebar logo
        if (frm.page.sidebar) {
            const sidebar = $(frm.page.sidebar);
            sidebar.find("#school-logo-box").remove();

            sidebar.prepend(`
                <div id="school-logo-box" style="
                    width:150px;height:150px;border:1px solid #d1d8dd;
                    margin:10px auto;display:flex;align-items:center;
                    justify-content:center;background:#fafbfc;">
                    ${frm.doc.school_logo ? `<img src="${frm.doc.school_logo}" style="max-width:100%;max-height:100%;">` : ""}
                </div>
            `);
        }

        // Students redirect
        setTimeout(() => {
            $(tabSelector).off("click").on("click", () => {
                if (frm.doc.school_code) {
                    frappe.set_route("List", "Students", {
                        school_code: ["=", frm.doc.school_code, true]
                    });
                }
            });
        }, 300);
    },

   
});


 

// ===============================
// 1. CSS MANAGEMENT
// ===============================
function inject_costing_scroll_css() {
    if (document.getElementById("costing-scroll-css")) return;

    $("<style id='costing-scroll-css'>")
        .html(`
            .costing-scroll-wrapper {
                width: 100%;
                overflow-x: auto;
                overflow-y: hidden;
                padding-bottom: 6px;
            }

            .costing-scroll-wrapper table {
                min-width: 1200px;
                white-space: nowrap;
            }

            .costing-scroll-wrapper th,
            .costing-scroll-wrapper td {
                text-align: center;
                vertical-align: middle;
            }

            .grid-form-body {
                overflow-y: auto !important;
            }
        `)
        .appendTo("head");
}

// ===============================
// 2. UI CONTROL FUNCTIONS
// ===============================
 

function set_school_code_dropdown(frm) {
    const field = frm.fields_dict.school_code;
    if (!field || !field.$input) return;

    frappe.call({
        method: "impressio.impressio.doctype.school.school.get_school_code_options",
        callback(r) {
            if (!r.message?.length) return;

            const input = field.$input[0];

            if (input.awesomplete) {
                input.awesomplete.destroy();
            }

            input.awesomplete = new Awesomplete(input, {
                list: r.message,
                minChars: 0,
                autoFirst: true
            });

            // 🔑 Always show full list on focus
            $(input)
                .off("focus")
                .on("focus", () => {
                    input.value = "";
                    input.awesomplete.evaluate();
                });

            // Commit value on blur
            $(input)
                .off("blur")
                .on("blur", function () {
                    const value = $(this).val();
                    if (value && frm.doc.school_code !== value) {
                        frappe.model.set_value(
                            frm.doctype,
                            frm.docname,
                            "school_code",
                            value
                        ).then(() => {
                            if (frm.is_new()) {
                                fetch_lead_data(frm);
                            }
                        });
                    }
                });
        }
    });
}



function lock_child_grid(frm, fieldname) {
    const grid = frm.fields_dict[fieldname]?.grid;
    if (!grid) return;

    grid.cannot_add_rows = true;
    grid.cannot_delete_rows = true;
    grid.only_sortable = true;

    setTimeout(() => {
        const w = grid.wrapper;
        w.find(".grid-add-row").hide();
        w.find(".grid-remove-rows").hide();
        w.find(".grid-row-open").hide();
        w.find(".grid-download").hide();
        w.find(".grid-upload").hide();
        w.find(".grid-footer").hide();
    }, 100);
}
 
function full_lock_child_grid(frm, fieldname) {
    const grid = frm.fields_dict[fieldname]?.grid;
    if (!grid) return;

    // Disable adding/deleting rows
    grid.cannot_add_rows = true;
    grid.cannot_delete_rows = true;

    // Prevent opening row dialog
    grid.only_sortable = true;

    // Disable all inputs in cells
    setTimeout(() => {
        const w = grid.wrapper;

        // Hide all UI buttons
        w.find(".grid-add-row").hide();
        w.find(".grid-remove-rows").hide();
        w.find(".grid-row-open").hide();
        w.find(".grid-download").hide();
        w.find(".grid-upload").hide();
        w.find(".grid-footer").hide();

        // Disable cell editing
        w.find("input, select, textarea").attr("disabled", true);

        // Optional: prevent double-click editing
        grid.rows.forEach(row => {
            row.row_toggle && row.row_toggle.off("click");
        });
    }, 100);
}


// ===============================
// 3. FORM DATA MANAGEMENT
// ===============================

function clear_form_data(frm) {

    
    // Existing clears
    frm.clear_table("uniform_details");
    frm.clear_table("uniform_detail_costing");
    frm.clear_table("books_details");
    frm.clear_table("books_details_costing");
    frm.clear_table("grades_details");

    // ✅ NEW: clear school coordinator
    frm.clear_table("school_coordinator");

    // ✅ NEW: clear general fields
    frm.set_value({
        uniform_details_checkbox: 0,
        books_details_checkbox: 0,

        street: "",
        city: "",
        state: "",
        country: "",
        pincode: "",
        school_name: "",
        branch_name: "",
    });


    frm.refresh_fields([
        "uniform_details",
        "uniform_detail_costing",
        "books_details",
        "books_details_costing",
        "grades_details",
        "school_coordinator"
    ]);

    console.log("Form data cleared");
}



// ===============================
// 4. DATA FETCHING
// ===============================

function fetch_lead_data(frm) {

    // if (!frm.is_new() || !frm.doc.school_code) {
    //     clear_form_data(frm);
    //     return;
    // }

     clear_form_data(frm);

    frappe.call({
        method: "impressio.impressio.doctype.school.school.get_school_lead_data",
        args: { school_code: frm.doc.school_code },
        freeze: true,
        callback(r) {
           

            if (!r.message || Object.keys(r.message).length === 0 || 
                (!r.message.uniform_table?.length && !r.message.books_table?.length)) {

                frappe.msgprint({
                    title: __('No Data Found'),
                    message: __('No lead data found for school code: {0}', [frm.doc.school_code]),
                    indicator: 'orange'
                });
                return;
            }

            const data = r.message;

            populate_school_general_data(frm, data || {});
            populate_uniform_table_safe(frm, data.uniform_table || []);
            populate_books_table_safe(frm, data.books_table || []);
            populate_grades_table(frm, data.grades_data || []);


            frappe.show_alert(__('Lead data loaded successfully'), 3);
        },
        error(r) {
            console.error("API Error:", r);
            frappe.msgprint(__("Error fetching lead data: ") + r.message);
            clear_form_data(frm);
        }
    });
}

 function fetch_full_lead_data() {
     

    frappe.call({
        method: "impressio.impressio.doctype.school.school.get_lead_data",
        args: { school_code: "code54"},
        freeze: true,
        callback(r) {
          

            const data = r.message; 


            frappe.show_alert(__('Lead data loaded successfully'), 3);
        },
        error(r) {
            console.error("API Error:", r); 
        }
    });
}

// ===============================
// 5. POPULATION FUNCTIONS
// ===============================

function populate_uniform_table_safe(frm, rows) {
    if (!rows || !rows.length) return;

    frm.clear_table("uniform_details");
    frm.clear_table("uniform_detail_costing");

    rows.forEach(r => {
        const key = generate_row_key();

        const u = frm.add_child("uniform_details");
        u.row_key = key;
        // Section 1
        // Col 1
        u.grade = r.grade;
        u.school_given_grade_name = r.school_given_grade_name;
        u.sections = r.sections;
        u.school_given_section_name = r.school_given_section_name;
        u.house_name = r.house_name;
        u.house_colour = r.house_colour;

        // Col 2 
        u.male = r.male || '';
        u.female = r.female || '';
        u.uniform_type = r.uniform_type || '';
        u.uniform_type_regular_uniform = r.uniform_type_regular_uniform;
        u.uniform_type_sports_uniform = r.uniform_type_sports_uniform;
        u.uniform_type_winter_uniform = r.uniform_type_winter_uniform;
        u.uniform_type_accessories = r.uniform_type_accessories;
        u.uniform_type_others = r.uniform_type_others;
        u.regular_uniform_type = r.regular_uniform_type;
        u.uniform_type_name = r.uniform_type_name;

        // Col 3
        u.price = r.price;
        u.fabric_type = r.fabric_type;
        u.sub_fabric_category_type = r.sub_fabric_category_type;
        u.selling_price = r.selling_price;
        u.msl = r.msl;
        u.remarks = r.remarks;

        // Section 2
        u.house_strength = r.house_strength;
        u.grade_strength = r.grade_strength;

        u.total_male_strength = r.total_male_strength;
        u.total_female_strength = r.total_female_strength;


        if (r.costing_details?.length) {
            r.costing_details.forEach(c => {
                const cd = frm.add_child("uniform_detail_costing");
                cd.grade = c.grade || "";
                cd.existing_uniform = c.existing_uniform || "";
                cd.product_name = c.product_name || "";
                cd.cost_price = c.cost_price || 0;
                cd.fixed_margin = c.fixed_margin || 0;
                cd.organization_price = c.organization_price || 0;
                cd.agreed_price_org = c.agreed_price_org || 0;
                cd.organization_margin = c.organization_margin || 0;
                cd.organization_mrp = c.organization_mrp || 0;
                cd.customer_discount = c.customer_discount || 0;
                cd.display_price = c.display_price || 0;
                cd.gst_inclusiveexclusive = c.gst_inclusiveexclusive || ""; 
                cd.parent_child_row = key; // reference parent row_key
            });
        }
    });

    frm.refresh_fields(["uniform_details", "uniform_detail_costing"]);
}

function populate_books_table_safe(frm, rows) {
    if (!rows || !rows.length) return;

    frm.clear_table("books_details");
    frm.clear_table("books_details_costing");

    rows.forEach(r => {
        const key = generate_row_key();

        const b = frm.add_child("books_details");
        // section 1
        // coll 1
        b.grade = r.grade;
        b.school_given_grade_name = r.school_given_grade_name;
        b.sections = r.sections;
        b.school_given_section_name = r.school_given_section_name;
        b.language = r.language;
        b.language_strength = r.language_strength;
        b.group_subject = r.group_subject;
        b.group_subject_strength = r.group_subject_strength;        

        //  col 2
        b.bundle_code = r.bundle_code;
        b.bundle_name = r.bundle_name;
        b.bundle_cost_price = r.bundle_cost_price;
        b.selling_price = r.selling_price;
        b.bundle_msl = r.bundle_msl;
        b.remarks = r.remarks;
        //  Section 2
        b.total_language_strength = r.total_language_strength;
        b.total_group_subject_strength = r.total_group_subject_strength;
        b.grade_strength = r.grade_strength;


        b.row_key = key;

        if (r.costing_details?.length) {
            r.costing_details.forEach(c => {
                const cd = frm.add_child("books_details_costing");
                cd.grade = c.grade || '';
                cd.existing_books = c.existing_books || '';
                cd.bundle_name = c.bundle_name || '';
                cd.sub_bundle_name = c.sub_bundle_name || '';
                cd.product_name = c.product_name || '';
                cd.qty = c.qty || 0;
                cd.cost_price = c.cost_price || 0.0;
                cd.fixed_margin = c.fixed_margin || 0.0;
                cd.organization_price = c.organization_price || 0.0;
                cd.agreed_price_org = c.agreed_price_org || 0.0;
                cd.organization_margin_price = c.organization_margin_price || 0.0;
                cd.organization_mrp = c.organization_mrp || 0.0;
                cd.customer_discount = c.customer_discount || 0.0;
                cd.display_price = c.display_price || 0.0;
                cd.gst_inclusiveexclusive = c.gst_inclusiveexclusive || "";
                cd.parent_child_row = key; // reference parent row_key  
            });
        }
    });

    frm.refresh_fields(["books_details", "books_details_costing"]);
}

function populate_grades_table(frm, gradesData) {
    if (!gradesData || !gradesData.length) return;

    frm.clear_table("grades_details");

    gradesData.forEach(r => {
        frm.add_child("grades_details", {
            grade: r.grade,
            school_given_grade_name: r.school_given_grade_name || "",
            sections: r.sections || ""
        });
    });

    frm.refresh_field("grades_details");
}


function populate_school_general_data(frm, data) {

    const customer = data.customer || {};
    const leadData = data.lead_general_data || {};

    if (!leadData || Object.keys(leadData).length === 0) {
        return;
    }

    // ------------------
    // COMMON
    // ------------------
    if (customer) {
        frm.set_value({
            branch_name: customer.custom_branch_name || ""
        });
    }
 
    console.log(leadData.common.company_name)

    if (leadData.common) {
        frm.set_value({
            uniform_details_checkbox: leadData.common.uniform_details_checkbox || 0,
            books_details_checkbox: leadData.common.books_details_checkbox || 0,
            school_name: leadData.common.company_name || "hello",
        });
    }

    // ------------------
    // ADDRESS
    // ------------------
    if (leadData.address) {
        frm.set_value({
            street: leadData.address.street || "",
            city: leadData.address.city || "",
            state: leadData.address.state || "",
            country: leadData.address.country || "",
            pincode: leadData.address.pincode || "",
        });
    }

    // ------------------
    // SCHOOL COORDINATOR
    // ------------------
    frm.clear_table("school_coordinator");

    if (leadData.school_coordinator?.length) {
        leadData.school_coordinator.forEach(r => {
            frm.add_child("school_coordinator", {
                poc_name: r.poc_name || "",
                email: r.email || "",
                contact_number: r.contact_number || "",
                alternate_number: r.alternate_number || "",
                role: r.role || ""
            });
        });
    }

    frm.refresh_field("school_coordinator");
}


// ===============================
// 6. COSTING VIEW RENDER FUNCTIONS
// ===============================
// Uniform Costing View
frappe.ui.form.on("School Uniform Details", {
    form_render(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        render_uniform_costing_view(frm, row);
    }
});

function render_uniform_costing_view(frm, parent_row) {
    const rows = (frm.doc.uniform_detail_costing || [])
        .filter(r => r.parent_child_row === parent_row.row_key);

    const grid_row = frm.fields_dict.uniform_details
        .grid.grid_rows_by_docname[parent_row.name];
    if (!grid_row) return;

    const wrapper = grid_row.grid_form.fields_dict.uniform_costing_html.$wrapper;
    wrapper.empty();

    let html = `
        <div class="costing-scroll-wrapper">
            <table class="table table-bordered small">
                <thead>
                    <tr>
                        <th>No</th>
                        <th>Grade</th>
                        <th>Existing Uniform</th>
                        <th>Product Name</th>
                        <th>Inventre Cost Price</th>
                        <th>Category Fixed Margin %</th>
                        <th>Suggested Organization Price</th>
                        <th>Agreed Price ORG.</th>
                        <th>Organization Margin %</th>
                        <th>Organization MRP</th>
                        <th>Customer Discount %</th>
                        <th>Display Price</th>
                        <th>GST Inclusive/Exclusive</th>
                    </tr>
                </thead>
                <tbody>
    `;

    if (!rows.length) {
        html += `<tr><td colspan="8" class="text-center">No data</td></tr>`;
    } else {
        rows.forEach((r, i) => {
            html += `
                <tr>
                    <td>${i + 1}</td>
                    <td>${r.grade}</td>
                    <td>${r.existing_uniform}</td>
                    <td>${r.product_name}</td>
                    <td>${r.cost_price}</td>
                    <td>${r.fixed_margin}</td>
                    <td>${r.organization_price}</td>
                    <td>${r.agreed_price_org}</td>
                    <td>${r.organization_margin}</td>
                    <td>${r.organization_mrp}</td>
                    <td>${r.customer_discount}</td>
                    <td>${r.display_price}</td>
                    <td>${r.gst_inclusiveexclusive}</td> 
                </tr>
            `;
        });
    }

    html += `</tbody></table></div>`;
    wrapper.html(html);
}

// Books Costing View
frappe.ui.form.on("School Books Details", {
    form_render(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        render_books_costing_view(frm, row);
    }
});

function render_books_costing_view(frm, parent_row) {
    const rows = (frm.doc.books_details_costing || [])
        .filter(r => r.parent_child_row === parent_row.row_key);

    const grid_row = frm.fields_dict.books_details
        .grid.grid_rows_by_docname[parent_row.name];
    if (!grid_row) return;

    const wrapper = grid_row.grid_form.fields_dict.books_costing_html.$wrapper;
    wrapper.empty();

    let html = `
        <div class="costing-scroll-wrapper">
            <table class="table table-bordered small">
                <thead>
                    <tr>
                        <th>No</th>
                        <th>Grade</th> 
                        <th>Existing Books</th> 
                        <th>Bundle Name</th> 
                        <th>Sub Bundle Name</th> 
                        <th>Product Name</th> 
                        <th>Qty</th> 
                        <th>Cost Price</th> 
                        <th>Fixed Margin %</th> 
                        <th>Organization Price</th> 
                        <th>Organization Margin %</th> 
                        <th>Organization MRP</th> 
                        <th>Customer Discount %</th> 
                        <th>Display Price</th>
                    </tr>
                </thead>
                <tbody>
    `;

    if (!rows.length) {
        html += `<tr><td colspan="11" class="text-center">No data</td></tr>`;
    } else {
        
        rows.forEach((r, i) => {
            html += `
                <tr>
                    <td>${i + 1}</td>
                    <td>${r.grade || ""}</td>
                    <td>${r.existing_books || ""}</td>
                    <td>${r.bundle_name || ""}</td>
                    <td>${r.sub_bundle_name || ""}</td>
                    <td>${r.product_name || ""}</td>
                    <td class="text-end">${r.qty ?? 0}</td>
                    <td class="text-end">${r.cost_price ?? 0}</td>
                    <td class="text-end">${r.fixed_margin ?? 0}</td>
                    <td class="text-end">${r.organization_price ?? 0}</td>
                    <td class="text-end">${r.organization_margin_price ?? 0}</td>
                    <td class="text-end">${r.organization_mrp ?? 0}</td>
                    <td class="text-end">${r.customer_discount ?? 0}</td>
                    <td class="text-end">${r.display_price ?? 0}</td>
                </tr>
            `;
        });
    }

    html += `</tbody></table></div>`;
    wrapper.html(html);
}
