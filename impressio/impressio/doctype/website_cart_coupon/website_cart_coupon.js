// =============================
// CONFIG
// =============================
let coupon_current_page = 1;
const PAGE_LENGTH = 10;


// =============================
// RENDER REPORT
// =============================
function render_coupon_report(frm, data){

    const summary = data.summary || {};
    const records = data.records || [];
    const total_records = data.total_records || 0;

    const last_page = Math.max(Math.ceil(total_records / PAGE_LENGTH), 1);

    let html = `
    <div style="padding:10px;">

        <!-- SUMMARY CARDS -->
        <div style="display:flex; gap:12px; margin-bottom:18px;">
            <div style="flex:1;background:#e6f4ff;border:1px solid #91caff;padding:12px;border-radius:10px;">
                <div style="font-size:12px;color:#0958d9;">Total Usage</div>
                <div style="font-size:22px;font-weight:700;color:#003eb3;">
                    ${summary.total_orders || 0}
                </div>
            </div>

            <div style="flex:1;background:#f6ffed;border:1px solid #b7eb8f;padding:12px;border-radius:10px;">
                <div style="font-size:12px;color:#237804;">Total Discount Given</div>
                <div style="font-size:22px;font-weight:700;color:#135200;">
                    ₹ ${summary.total_discount || 0}
                </div>
            </div>
        </div>
    `;


    // ---------------- NO RECORDS ----------------
    if(!records.length){
        html += `
        <div style="
            padding:20px;
            background:#fff7e6;
            border:1px solid #ffd591;
            border-radius:10px;
            text-align:center;
            color:#ad6800;">
            Coupon has not been used yet
        </div></div>`;

        frm.fields_dict.redeemed_customers.$wrapper.html(html);
        return;
    }


    // ---------------- TABLE ----------------
    html += `
    <table class="table table-bordered" style="font-size:13px;">
        <thead style="background:#fafafa;">
            <tr>
                <th>Sales Order</th>
                <th>Customer</th>
                <th>Date</th>
                <th>Order Amount</th>
                <th>Discount</th>
            </tr>
        </thead>
        <tbody>
    `;

    records.forEach(r => {
        html += `
        <tr>
            <td>
                <a href="/app/sales-order/${r.name}" target="_blank">
                    ${r.name}
                </a>
            </td>

            <td>
                <a href="/app/customer/${r.customer}" target="_blank">
                    ${r.customer}
                </a>
            </td>

            <td>${r.transaction_date || ""}</td>
            <td>₹ ${r.grand_total || 0}</td>

            <td style="color:green;font-weight:bold;">
                ₹ ${r.discount_amount || 0}
            </td>
        </tr>`;
    });

    html += `</tbody></table>`;


    // ---------------- PAGINATION ----------------
    html += `
    <div style="margin-top:18px;text-align:center;">

        <button class="btn btn-xs btn-default prev-page"
            ${coupon_current_page <= 1 ? "disabled" : ""}>
            Previous
        </button>

        <span style="margin:0 12px;font-weight:600;">
            Page ${coupon_current_page} of ${last_page}
        </span>

        <button class="btn btn-xs btn-default next-page"
            ${coupon_current_page >= last_page ? "disabled" : ""}>
            Next
        </button>

    </div>
    </div>
    `;

    frm.fields_dict.redeemed_customers.$wrapper.html(html);


    // ---------------- BUTTON EVENTS ----------------

    const wrapper = frm.fields_dict.redeemed_customers.$wrapper;

    wrapper.find(".prev-page").off("click").on("click", () => {
        if(coupon_current_page <= 1) return;
        coupon_current_page--;
        load_coupon_page(frm);
    });

    wrapper.find(".next-page").off("click").on("click", () => {
        if(coupon_current_page >= last_page) return;
        coupon_current_page++;
        load_coupon_page(frm);
    });
}



// =============================
// LOAD DATA FROM API
// =============================
function load_coupon_page(frm){

    if(frm.is_new()) return;

    frappe.call({
        method: "impressio.impressio.doctype.website_cart_coupon.website_cart_coupon.get_coupon_usage_data",
        args: {
            coupon_name: frm.doc.name,
            page: coupon_current_page,
            page_length: PAGE_LENGTH
        },
        freeze: false,
        callback: function(r){
            if(r.message){
                render_coupon_report(frm, r.message);
            }
        }
    });
}



// =============================
// FORM EVENTS
// =============================
frappe.ui.form.on("Website Cart Coupon", {

    // checkbox mutual rule
    one_time_use(frm){
        if(frm.doc.one_time_use){
            frm.set_value("can_use_multiple_times", 0);
        }
    },

    can_use_multiple_times(frm){
        if(frm.doc.can_use_multiple_times){
            frm.set_value("one_time_use", 0);
        }
    },


    // NEW DOCUMENT
    onload(frm){
        if(frm.is_new() && frm.fields_dict.redeemed_customers){
            frm.fields_dict.redeemed_customers.$wrapper.html(`
                <div style="
                    padding:18px;
                    background:#fafafa;
                    border:1px dashed #d9d9d9;
                    border-radius:8px;
                    text-align:center;
                    color:#999;">
                    Save the coupon to see usage report
                </div>
            `);
        }
    },


    // AFTER SAVE → LOAD REPORT
    after_save(frm){
        coupon_current_page = 1;
        load_coupon_page(frm);
    },


    // EXISTING DOCUMENT
    refresh(frm){

        if(frm.is_new()){
            frm.fields_dict.redeemed_customers.$wrapper.html(`
                <div style="
                    padding:18px;
                    background:#fafafa;
                    border:1px dashed #d9d9d9;
                    border-radius:8px;
                    text-align:center;
                    color:#999;">
                    Save the coupon to see usage report
                </div>
            `);
            return;
        }

        coupon_current_page = 1;
        load_coupon_page(frm);
    }

});
