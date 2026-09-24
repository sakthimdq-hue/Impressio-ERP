function loadVueAndInit(callback) {
	if (typeof Vue !== "undefined") {
		console.log("✅ Vue already loaded");
		callback();
		return;
	}

	let script = document.createElement("script");
	script.src = "https://unpkg.com/vue@3/dist/vue.global.prod.js";
	script.defer = true;

	script.onload = () => {
		console.log("✅ Vue 3 Loaded from CDN");
		callback();
	};

	document.head.appendChild(script);
}

// Create Vue app
window.createVueReadingsApp = function (targetId, frm) {
	loadVueAndInit(() => {
		const { createApp, ref, watch, computed } = Vue;

		//  Debounce function
		function debounce(fn, delay = 300) {
			let timeout;
			return (...args) => {
				clearTimeout(timeout);
				timeout = setTimeout(() => fn(...args), delay);
			};
		}

		async function fetchParameters() {
			const res = await frappe.call({
				method: "impressio.impressio_transaction.get_method.qr_code.get_parameter",
			});
			return res.message || [];
		}

		const app = createApp({
			setup() {
				const readings = ref([]);
				const selectAll = ref(false);

				(async () => {
					// If already has saved readings, load them
					if ((frm.doc.readings || []).length) {
						readings.value = frm.doc.readings.map((r) => ({
							parameter: r.parameter,
							status: r.accepted ? "accepted" : r.rejected ? "rejected" : "",
							reading_value: r.reading_value || "",
							selected: false,
							showMenu: false,
						}));
					} else {
						// Fetch and populate parameters
						const params = await fetchParameters();
						readings.value = params.map((p) => ({
							parameter: p.parameter,
							status: "",
							reading_value: "",
							selected: false,
							showMenu: false,
						}));
					}
				})();

				const toggleAll = () => {
					readings.value.forEach((r) => (r.selected = selectAll.value));
				};

				const anySelected = computed(() => readings.value.some((r) => r.selected));

				const deleteSelected = () => {
					readings.value = readings.value.filter((r) => !r.selected);
					selectAll.value = false;
				};

				const addRow = () => {
					readings.value.push({
						parameter: "",
						status: "",
						reading_value: "",
						selected: false,
						showMenu: false,
					});
				};

				const insertAbove = (index) => {
					readings.value.splice(index, 0, {
						parameter: "",
						status: "",
						reading_value: "",
						selected: false,
						showMenu: false,
					});
				};

				const insertBelow = (index) => {
					readings.value.splice(index + 1, 0, {
						parameter: "",
						status: "",
						reading_value: "",
						selected: false,
						showMenu: false,
					});
				};

				const duplicateRow = (index) => {
					const row = JSON.parse(JSON.stringify(readings.value[index]));
					row.selected = false;
					row.showMenu = false;
					readings.value.splice(index + 1, 0, row);
				};

				const deleteRow = (index) => {
					readings.value.splice(index, 1);
				};

				const moveUp = (index) => {
					if (index > 0) {
						const temp = readings.value[index];
						readings.value.splice(index, 1);
						readings.value.splice(index - 1, 0, temp);
					}
				};

				const moveDown = (index) => {
					if (index < readings.value.length - 1) {
						const temp = readings.value[index];
						readings.value.splice(index, 1);
						readings.value.splice(index + 1, 0, temp);
					}
				};

				const toggleMenu = (r) => {
					readings.value.forEach((row) => (row.showMenu = false));
					r.showMenu = !r.showMenu;
				};

				const isReadOnly = frm.doc.docstatus === 1;

				// Close menu on outside click
				document.addEventListener("click", (e) => {
					if (!e.target.closest(".menu-wrapper")) {
						readings.value.forEach((r) => (r.showMenu = false));
					}
				});

				// Debounced sync with Frappe child table
				const syncWithFrappe = debounce((newVal) => {
					frm.clear_table("readings");
					newVal.forEach((r) => {
						let child = frm.add_child("readings");
						child.parameter = r.parameter;
						child.accepted = r.status === "accepted" ? 1 : 0;
						child.rejected = r.status === "rejected" ? 1 : 0;
						child.reading_value = r.reading_value;
					});
					frm.refresh_field("readings");
					frm.dirty();
				}, 500);

				watch(readings, syncWithFrappe, { deep: true });

				return {
					readings,
					addRow,
					selectAll,
					toggleAll,
					anySelected,
					deleteSelected,
					insertAbove,
					insertBelow,
					duplicateRow,
					deleteRow,
					moveUp,
					moveDown,
					toggleMenu,
					isReadOnly,
				};
			},

			template: `
				<div class="p-3">
					<table class="table table-bordered" style="width:100%; border-collapse:collapse; background:#fff; font-size:13px;">
						<thead style="color:#7c7c7c; background-color:#f3f3f3;">
							<tr>
								<th style="width:4%; text-align:center;">
									<input type="checkbox" v-model="selectAll" @change="toggleAll" :disabled="isReadOnly" />
								</th>
								<th style="width:5%; text-align:center;">No.</th>
								<th style="width:35%;">Parameter <span style="color:red;">*</span></th>
								<th style="width:25%; text-align:center;">Status</th>
								<th style="width:25%;">Reading Value</th>
								<th style="width:5%; text-align:center;"> <i class="fa fa-cog" aria-hidden="true"></i></th>
							</tr>
						</thead>

						<tbody>
							<tr v-for="(r, i) in readings" :key="i">
								<td class="text-center">
									<input type="checkbox" v-model="r.selected" :disabled="isReadOnly" />
								</td>
								<td class="text-center">{{ i + 1 }}</td>
								<td>
									<input
										v-model="r.parameter"
										type="text"
										:disabled="isReadOnly"
										placeholder="Enter parameter"
										class="form-control"
										style="border:none; border-radius:0; background-color:#fff;
											   box-shadow:none; padding:4px 8px; width:100%;"
									/>
								</td>
								<td class="text-center">
									<div class="d-flex justify-content-center align-items-center" style="gap:20px;">
										<label class="form-check d-flex align-items-center mb-0" style="gap:6px;">
											<input
												type="radio"
												class="form-check-input"
												:name="'status-' + i"
												value="accepted"
												v-model="r.status"
												:disabled="isReadOnly"
											/>
											<span>Accepted</span>
										</label>
										<label class="form-check d-flex align-items-center mb-0" style="gap:6px;">
											<input
												type="radio"
												class="form-check-input"
												:name="'status-' + i"
												value="rejected"
												v-model="r.status"
												:disabled="isReadOnly"
											/>
											<span>Rejected</span>
										</label>
									</div>
								</td>
								<td>
									<input
										v-model="r.reading_value"
										type="text"
										:disabled="isReadOnly"
										placeholder="Enter value"
										class="form-control"
										style="border:none; border-radius:0; background-color:#fff;
											   box-shadow:none; padding:4px 8px; width:100%;"
									/>
								</td>
								<td class="text-center menu-wrapper" style="position:relative;">
									<button v-if="!isReadOnly" class="btn btn-sm btn-light" @click.stop="toggleMenu(r)" >
										<i class="fa fa-pencil" aria-hidden="true"></i>
									</button>
									<div v-if="r.showMenu" class="card shadow-sm" 
										 style="position:absolute; right:30px; top:0; z-index:10; min-width:160px;">
										<ul class="list-group list-group-flush">
											<li class="list-group-item list-group-item-action" @click="insertAbove(i)">Insert Above</li>
											<li class="list-group-item list-group-item-action" @click="insertBelow(i)">Insert Below</li>
											<li class="list-group-item list-group-item-action" @click="duplicateRow(i)">Duplicate</li>
											<li class="list-group-item list-group-item-action text-danger" @click="deleteRow(i)">Delete</li>
											<li class="list-group-item list-group-item-action" @click="moveUp(i)">Move Up</li>
											<li class="list-group-item list-group-item-action" @click="moveDown(i)">Move Down</li>
										</ul>
									</div>
								</td>
							</tr>
						</tbody>
					</table>

					<div class="d-flex justify-content-between align-items-center mt-2">
						<button @click="addRow" class="btn btn-sm btn-secondary" :disabled="isReadOnly">
							Add Row
						</button>
						<button
							v-if="anySelected && !isReadOnly"
							@click="deleteSelected"
							class="btn btn-sm btn-danger"
						>
							<i class="fa fa-trash"></i> Delete
						</button>
					</div>
				</div>
			`,
		});

		app.mount(`#${targetId}`);
	});
};
