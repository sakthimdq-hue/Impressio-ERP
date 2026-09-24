frappe.provide("impressio.pagination");

(() => {
    // Inject custom styles for the text box and buttons
    function inject_styles() {
        if (document.getElementById("npg-style")) return;
        const s = document.createElement("style");
        s.id = "npg-style";
        s.textContent = `
.npg-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    flex-wrap: wrap;
}
.npg-input {
    width: 120px;
    height: 28px;
    border: 1px solid #dadce0;
    border-radius: 4px;
    padding: 0 6px;
    font-size: 13px;
    text-align: center;
    outline: none;
    color: #3c4043;
}
.npg-input:focus {
    border-color: #1a73e8;
}
.npg-row-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0 14px;
    height: 36px;
    border: 1px solid #dadce0;
    border-radius: 18px;
    background: transparent;
    font-size: 14px;
    color: #3c4043;
    cursor: pointer;
    transition: background .15s;
    white-space: nowrap;
}
.npg-row-btn:hover:not([disabled]) {
    background: #f8f9fa;
}
// .npg-row-btn.active {
//     background: #e8f0fe;
//     color: #1a73e8;
//     font-weight: 600;
// }
.npg-row-btn[disabled] {
    color: #bbb;
    border-color: #e8e8e8;
    cursor: default;
    pointer-events: none;
}
        `;
        document.head.appendChild(s);
    }

    // Main patching function
    function patch_when_ready() {
        const BL = frappe.views.ListView;
        if (!BL || BL.__npg_patched) return;
        BL.__npg_patched = true;

        inject_styles();

        // Save original functions
        const _orig_refresh = BL.prototype.refresh;
        const _orig_setup_paging = BL.prototype.setup_paging_area;
        const _orig_get_args = BL.prototype.get_args;

        // Override get_args to enforce dynamic page length and start with 20
        BL.prototype.get_args = function() {
            const args = _orig_get_args.call(this);
            args.page_length = this.__npg_page_length || args.page_length || 20; // Start with 20
            args.start = this.__npg_start || 0;
            return args;
        };

        // Override refresh to reset pagination on filter changes
        BL.prototype.refresh = function() {
            const sig = JSON.stringify(
                this.get_filters ? this.get_filters() :
                this.filter_area ? this.filter_area.get() : []
            );
            if (this.__npg_filter_sig !== sig) {
                this.__npg_filter_sig = sig;
                this.__npg_total = null;
                this.__npg_start = 0;
                this.__npg_page_length = 20; // Reset to 20
                this.start = 0;
            }
            return _orig_refresh.apply(this, arguments);
        };

        // Custom setup_paging_area to include both text box and standard buttons
        BL.prototype.setup_paging_area = function() {
            if (this.__npg_building) return;
            const me = this;

            // Resolve total count
            const fresh = me.total_count || 0;

            // Wait and retry if data is not ready
            if (fresh === 0 && !(me.data && me.data.length)) {
                if (!me.$paging_area) _orig_setup_paging.call(me);
                if (!me.__npg_retried) {
                    me.__npg_retried = true;
                    clearTimeout(me.__npg_retry);
                    me.__npg_retry = setTimeout(() => {
                        me.__npg_building = false;
                        me.setup_paging_area();
                    }, 600);
                } else {
                    me.__npg_retried = false;
                    if (me.$paging_area) me.$paging_area.empty();
                }
                return;
            }

            // Set total and reset retry flag
            if (fresh > 0) me.__npg_total = fresh;
            if (!me.__npg_total) me.__npg_total = fresh;
            me.__npg_retried = false;

            // Ensure paging_area exists
            if (!me.$paging_area) _orig_setup_paging.call(me);
            me.$paging_area.empty();
            me.__npg_building = true;

            // Build DOM for both text box and standard buttons
            const $wrap = $(`<div class="npg-wrap"></div>`);

            // Add a text box for manual batch selection
            const $input = $(`
                <input
                    type="text"
                    class="npg-input"
                    placeholder="Enter batch (e.g. 11-30)"
                >
            `);

            // Add event listener for Enter key
            $input.on("keydown", function(e) {
                if (e.key === "Enter") {
                    const batch = $(this).val().trim();
                    if (!batch) {
                        // If empty, show first 20 records
                        me.__npg_start = 0;
                        me.__npg_page_length = 20;
                        me.start = 0;
                        me.refresh();
                        return;
                    }

                    // Split batch range into start and end
                    const [startStr, endStr] = batch.split("-");
                    const start = parseInt(startStr.trim());
                    const end = parseInt(endStr.trim());

                    // Calculate page length dynamically
                    const page_length = end - start + 1;

                    // Calculate new start position (0-based)
                    const new_start = start - 1;

                    // Update start position and page length
                    me.__npg_start = new_start;
                    me.__npg_page_length = page_length;
                    me.start = new_start;

                    // Clear stale rows
                    if (me.data) me.data = [];
                    if (me.list_view && me.list_view.data) me.list_view.data = [];
                    me.$result && me.$result.find(".list-row, .frappe-list-rows").empty();

                    // Refresh with new start position and page length
                    me.refresh();
                }
            });

            $wrap.append($input);

            // Add standard pagination buttons (10, 20, 50, 100, 500, 1000)
            const standardPages = [10, 20, 50, 100, 500, 1000];
            standardPages.forEach(page => {
                const $btn = $(`<button class="npg-row-btn">${page}</button>`);
                if (me.page_length === page) {
                    $btn.addClass("active");
                }
                $btn.on("click", () => {
                    me.__npg_page_length = page;
                    me.page_length = page;
                    me.__npg_start = 0;
                    me.start = 0;
                    if (me.list_view) me.list_view.start = 0;
                    if (me.args) me.args.start = 0;
                    me.refresh();
                });
                $wrap.append($btn);
            });

            me.$paging_area.append($wrap);
            me.__npg_building = false;
        };
    }

    // Initialize patching when Frappe is ready
    if (window.frappe) {
        frappe.after_ajax(() => patch_when_ready());
        patch_when_ready();
    }
})();