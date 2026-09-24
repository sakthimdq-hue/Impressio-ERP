function show_asn_filter_results(data) {
    function get_completion_indicator(percentage) {
        if (percentage >= 75) return 'green';
        if (percentage >= 50) return 'blue';
        if (percentage > 0) return 'orange';
        return 'red';
    }
    
    let dialog = new frappe.ui.Dialog({
        title: __("Stock Availability Analysis"),
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'asn_results_html'
            }
        ],
        size: 'extra-large',
        primary_action_label: __('Apply Filter'),
        primary_action: function() {
            if (data.order_names && data.order_names.length > 0) {
                frappe.views.list_view['Order Processing Against Website Orders'].filter_area.clear();
                frappe.views.list_view['Order Processing Against Website Orders'].filter_area.add([
                    ["Order Processing Against Website Orders", "name", "in", data.order_names]
                ]);
                frappe.views.list_view['Order Processing Against Website Orders'].refresh();
                
                frappe.show_alert({
                    message: __("Filter applied to {0} orders", [data.order_names.length]),
                    indicator: 'green'
                }, 5);
            }
            dialog.hide();
        }
    });
    
    let html = `
        <style>
            .availability-modal {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            
            /* Summary Section */
            .summary-grid {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 15px;
                margin-bottom: 20px;
            }
            
            .summary-card {
                background: white;
                border-radius: 8px;
                padding: 15px;
                border: 1px solid #e0e0e0;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                text-align: center;
            }
            
            .summary-value {
                font-size: 28px;
                font-weight: 700;
                line-height: 1;
                margin-bottom: 5px;
            }
            
            .summary-label {
                font-size: 13px;
                color: #666;
                font-weight: 500;
            }
            
            /* Order Card */
            .order-card {
                background: white;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 20px;
                border: 1px solid #e0e0e0;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            }
            
            .order-header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 1px solid #f0f0f0;
            }
            
            .order-info h4 {
                margin: 0 0 5px 0;
                color: #333;
                font-weight: 600;
            }
            
            .customer-name {
                color: #666;
                font-size: 14px;
                margin-bottom: 8px;
            }
            
            .order-stats {
                display: flex;
                gap: 15px;
                font-size: 13px;
                color: #777;
            }
            
            .order-actions {
                text-align: right;
                min-width: 150px;
            }
            
            .completion-indicator {
                display: inline-block;
                padding: 6px 12px;
                background: #f8f9fa;
                border-radius: 6px;
                font-weight: 600;
                font-size: 14px;
                margin-bottom: 10px;
            }
            
            /* Item Table */
            .items-table {
                width: 100%;
                border-collapse: collapse;
            }
            
            .items-table th {
                background: #f8f9fa;
                padding: 12px 15px;
                text-align: left;
                font-weight: 600;
                color: #555;
                border-bottom: 2px solid #e0e0e0;
                font-size: 13px;
            }
            
            .items-table td {
                padding: 15px;
                border-bottom: 1px solid #f0f0f0;
                vertical-align: top;
            }
            
            .items-table tr:hover {
                background: #f9f9f9;
            }
            
            /* Item Details */
            .item-code {
                font-weight: 600;
                color: #333;
                margin-bottom: 3px;
            }
            
            .item-name {
                font-size: 12px;
                color: #777;
            }
            
            .quantity-cell {
                min-width: 120px;
            }
            
            .quantity-value {
                font-size: 16px;
                font-weight: 600;
                margin-bottom: 3px;
            }
            
            .quantity-label {
                font-size: 11px;
                color: #888;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .available {
                color: #28a745;
            }
            
            .shortage {
                color: #dc3545;
            }
            
            .warehouse-info, .asn-info {
                font-size: 12px;
                color: #666;
                margin-top: 3px;
            }
            
            /* Status Badges */
            .status-badge {
                display: inline-block;
                padding: 4px 10px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 500;
            }
            
            .badge-success {
                background: #d4edda;
                color: #155724;
            }
            
            .badge-warning {
                background: #fff3cd;
                color: #856404;
            }
            
            .badge-danger {
                background: #f8d7da;
                color: #721c24;
            }
            
            .badge-info {
                background: #d1ecf1;
                color: #0c5460;
            }
            
            /* No Data */
            .no-data {
                text-align: center;
                padding: 60px 20px;
                color: #999;
            }
            
            .no-data i {
                font-size: 48px;
                margin-bottom: 15px;
                opacity: 0.3;
            }
            
            /* Scroll Container */
            .scroll-container {
                max-height: 60vh;
                overflow-y: auto;
                padding-right: 10px;
            }
            
            .scroll-container::-webkit-scrollbar {
                width: 6px;
            }
            
            .scroll-container::-webkit-scrollbar-track {
                background: #f1f1f1;
                border-radius: 3px;
            }
            
            .scroll-container::-webkit-scrollbar-thumb {
                background: #c1c1c1;
                border-radius: 3px;
            }
            
            /* Buttons */
            .action-btn {
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: 500;
                font-size: 13px;
                border: none;
                cursor: pointer;
                transition: all 0.2s;
            }
            
            .btn-primary {
                background: #007bff;
                color: white;
            }
            
            .btn-primary:hover {
                background: #0056b3;
            }
            
            .btn-info {
                background: #17a2b8;
                color: white;
            }
            
            .btn-info:hover {
                background: #117a8b;
            }
            
            /* Responsive */
            @media (max-width: 768px) {
                .summary-grid {
                    grid-template-columns: repeat(2, 1fr);
                }
                
                .order-header {
                    flex-direction: column;
                    gap: 15px;
                }
                
                .order-actions {
                    text-align: left;
                }
            }
        </style>
        
        <div class="availability-modal">
            <!-- Summary Section -->
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="summary-value" style="color: #007bff;">${data.orders ? data.orders.length : 0}</div>
                    <div class="summary-label">Total Orders</div>
                </div>
                <div class="summary-card">
                    <div class="summary-value" style="color: #28a745;">${data.total_items_with_stock || 0}</div>
                    <div class="summary-label">Items Available</div>
                </div>
                <div class="summary-card">
                    <div class="summary-value" style="color: #dc3545;">${data.total_items_missing_stock || 0}</div>
                    <div class="summary-label">Items Missing</div>
                </div>
                <div class="summary-card">
                    <div class="summary-value" style="color: #fd7e14;">${data.total_shortage_all_orders || 0}</div>
                    <div class="summary-label">Total Shortage</div>
                </div>
            </div>
            
            <!-- Orders List -->
            <div class="scroll-container">
    `;
    
    if (!data.orders || data.orders.length === 0) {
        html += `
                <div class="no-data">
                    <i class="fa fa-search"></i>
                    <h4>No Orders Found</h4>
                    <p>No orders match the current criteria</p>
                </div>
        `;
    } else {
        data.orders.forEach(order => {
            // Determine order status
            let orderStatus = '';
            let statusClass = '';
            if (order.can_fulfill_all) {
                orderStatus = 'All Items Available';
                statusClass = 'badge-success';
            } else if (order.can_fulfill_some) {
                orderStatus = 'Partial Availability';
                statusClass = 'badge-warning';
            } else {
                orderStatus = 'No Stock Available';
                statusClass = 'badge-danger';
            }
            
            html += `
                <div class="order-card">
                    <div class="order-header">
                        <div class="order-info">
                            <h4>${order.order_no || 'No Order Number'}</h4>
                            <div class="customer-name">
                                <i class="fa fa-user"></i> ${order.customer_name || 'No Customer'}
                            </div>
                            <div class="order-stats">
                                <span>
                                    <i class="fa fa-cube"></i> ${order.fulfillable_items || 0}/${order.total_items || 0} items available
                                </span>
                                ${order.total_shortage > 0 ? `
                                    <span style="color: #dc3545;">
                                        <i class="fa fa-exclamation-triangle"></i> ${order.total_shortage} shortage
                                    </span>
                                ` : ''}
                                <span class="status-badge ${statusClass}">
                                    ${orderStatus}
                                </span>
                            </div>
                        </div>
                        <div class="order-actions">
                            <div class="completion-indicator ${get_completion_indicator(order.completion_percentage || 0)}">
                                ${order.completion_percentage || 0}% Complete
                            </div>
                            <div style="display: flex; gap: 8px;">
                                <button class="action-btn btn-primary" 
                                    onclick="frappe.set_route('Form', 'Order Processing Against Website Orders', '${order.name}')">
                                    Open Order
                                </button>
                                ${order.asn_no ? `
                                    <button class="action-btn btn-info" 
                                        onclick="frappe.set_route('Form', 'ASN Creation', '${order.asn_no}')">
                                        View ASN
                                    </button>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                    
                    <!-- Items Table -->
                    <table class="items-table">
                        <thead>
                            <tr>
                                <th width="25%">Item</th>
                                <th width="25%">Order Qty</th>
                                <th width="25%">Warehouse Qty</th>
                                <th width="25%">ASN Qty</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            if (order.items && order.items.length > 0) {
                order.items.forEach(item => {
                    // Determine availability
                    const whAvailable = item.warehouse_qty >= item.order_qty;
                    const asnAvailable = item.asn_pending_qty >= item.order_qty;
                    const anyAvailable = whAvailable || asnAvailable;
                    
                    html += `
                        <tr>
                            <td>
                                <div class="item-code">${item.item_code || 'N/A'}</div>
                                <div class="item-name">${item.item_name || ''}</div>
                                ${item.warehouse ? `
                                    <div class="warehouse-info">
                                        <i class="fa fa-warehouse"></i> ${item.warehouse}
                                    </div>
                                ` : ''}
                                ${item.asn_name ? `
                                    <div class="asn-info">
                                        <i class="fa fa-truck"></i> ${item.asn_name}
                                    </div>
                                ` : ''}
                            </td>
                            <td class="quantity-cell">
                                <div class="quantity-value">${item.order_qty || 0}</div>
                                <div class="quantity-label">Ordered</div>
                            </td>
                            <td class="quantity-cell">
                                <div class="quantity-value ${whAvailable ? 'available' : 'shortage'}">
                                    ${item.warehouse_qty || 0}
                                    ${!whAvailable && item.order_qty ? ` (-${item.order_qty - item.warehouse_qty})` : ''}
                                </div>
                                <div class="quantity-label">In Warehouse</div>
                                ${whAvailable ? '<div style="color: #28a745; font-size: 11px;">✓ Available</div>' : ''}
                            </td>
                            <td class="quantity-cell">
                                <div class="quantity-value ${asnAvailable ? 'available' : 'shortage'}">
                                    ${item.asn_pending_qty || 0}
                                    ${!asnAvailable && item.order_qty ? ` (-${item.order_qty - item.asn_pending_qty})` : ''}
                                </div>
                                <div class="quantity-label">In ASN</div>
                                ${asnAvailable ? '<div style="color: #28a745; font-size: 11px;">✓ Available</div>' : ''}
                            </td>
                        </tr>
                    `;
                });
            } else {
                html += `
                    <tr>
                        <td colspan="4" style="text-align: center; color: #999; padding: 30px;">
                            No items found in this order
                        </td>
                    </tr>
                `;
            }
            
            html += `
                        </tbody>
                    </table>
                </div>
            `;
        });
    }
    
    html += `
            </div> <!-- End scroll container -->
        </div>
    `;
    
    dialog.fields_dict.asn_results_html.$wrapper.html(html);
    
    // Adjust modal size
    dialog.$wrapper.css({
        'width': '95%',
        'max-width': '1400px',
        'margin': '20px auto'
    });
    
    dialog.show();
}




frappe.listview_settings['Order Processing Against Website Orders'] = {
    onload(listview) {
        console.log('Order Processing listview loaded - ASN filter button should appear');
        
        // Function: remove highlight from all buttons
        function reset_button_styles() {
            listview.page.inner_toolbar.find('button').removeClass('btn-primary').addClass('btn-default');
        }

        // Function: highlight selected button
        function highlight(btn) {
            reset_button_styles();
            $(btn).removeClass('btn-default').addClass('btn-primary');
        }

        // Function: Show active filter text on the list view page
        function show_active_filter(text) {
            listview.page.set_indicator(text, "blue");
        }

        // === COMPLETION FILTERS ===
        // === 0–50% Completed ===
        listview.page.add_inner_button(__('0-50% Completed'), function (btn) {
            listview.filter_area.clear();
            listview.filter_area.add([
                ["Order Processing Against Website Orders", "completion_percentage", ">=", 0],
                ["Order Processing Against Website Orders", "completion_percentage", "<=", 49]
            ]);
            listview.refresh();

            highlight(btn);
            show_active_filter("0–50% Completed");
        }, __('Completion Filters'));

        // === 50–75% Completed ===
        listview.page.add_inner_button(__('50-75% Completed'), function (btn) {
            listview.filter_area.clear();
            listview.filter_area.add([
                ["Order Processing Against Website Orders", "completion_percentage", ">=", 49],
                ["Order Processing Against Website Orders", "completion_percentage", "<=", 75]
            ]);
            listview.refresh();

            highlight(btn);
            show_active_filter("50–75% Completed");
        }, __('Completion Filters'));

        // === 75–100% Completed ===
        listview.page.add_inner_button(__('75-100% Completed'), function (btn) {
            listview.filter_area.clear();
            listview.filter_area.add([
                ["Order Processing Against Website Orders", "completion_percentage", ">=", 75],
                ["Order Processing Against Website Orders", "completion_percentage", "<=", 100]
            ]);
            listview.refresh();

            highlight(btn);
            show_active_filter("75–100% Completed");
        }, __('Completion Filters'));

        // === Fully Completed ===
        listview.page.add_inner_button(__('Fully Completed'), function (btn) {
            listview.filter_area.clear();
            listview.filter_area.add([
                ["Order Processing Against Website Orders", "completion_percentage", "==", 100]
            ]);
            listview.refresh();

            highlight(btn);
            show_active_filter("Fully Completed");
        }, __('Completion Filters'));

        // === ASN AVAILABILITY FILTER ===
        listview.page.add_inner_button(__('ASN Available'), function (btn) {
            highlight(btn);
            
            // Fetch and filter orders with ASN availability
            frappe.call({
                method: "impressio.material_out.doctype.order_processing_against_website_orders.order_processing_against_website_orders.filter_by_asn_availability",
                callback: function(r) {
                    console.log('ASN filter response:', r);
                    if (r.message) {
                        show_asn_filter_results(r.message);
                        show_active_filter("ASN Available Orders");
                    }
                },
                error: function(err) {
                    console.error("Error fetching ASN availability:", err);
                    frappe.show_alert({
                        message: __("Error checking ASN availability"),
                        indicator: 'red'
                    }, 5);
                }
            });
        }, __('Completion Filters'));

        // === Reset Filters ===
        listview.page.add_inner_button(__('Reset Filters'), function (btn) {
            listview.filter_area.clear();
            listview.refresh();

            reset_button_styles();
            show_active_filter("No Filter");
        }, __('Completion Filters'));

        // === TRANSIT FILTERS ===
        // listview.page.add_inner_button('Arrived', function () {
        //     highlight(this);
        //     listview.filter_area.clear();
        //     listview.filter_area.add([
        //         ["Order Processing Against Website Orders", "transit_status", "=", "Arrived"]
        //     ]);
        //     listview.refresh();
        //     show_active_filter("Arrived Orders");
        // }, "Transit Filters");

        // listview.page.add_inner_button('In Transit', function () {
        //     highlight(this);
        //     listview.filter_area.clear();
        //     listview.filter_area.add([
        //         ["Order Processing Against Website Orders", "transit_status", "=", "In Transit"]
        //     ]);
        //     listview.refresh();
        //     show_active_filter("In Transit Orders");
        // }, "Transit Filters");

        // listview.page.add_inner_button('Delivered', function () {
        //     highlight(this);
        //     listview.filter_area.clear();
        //     listview.filter_area.add([
        //         ["Order Processing Against Website Orders", "transit_status", "=", "Delivered"]
        //     ]);
        //     listview.refresh();
        //     show_active_filter("Delivered Orders");
        // }, "Transit Filters");

        // // === ALL (Reset Transit Filters) ===
        // listview.page.add_inner_button('All', function () {
        //     highlight(this);
        //     listview.filter_area.clear();
        //     listview.refresh();
        //     show_active_filter("No Filter");
        // }, "Transit Filters");
    }
};