frappe.listview_settings['Stock Entry'] = {
   refresh(listview) {
      $('.filter-selector').hide();
   },
   onload(listview) {
      $('.filter-selector').hide();
   }
};