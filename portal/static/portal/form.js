/*
 * PEER portal -- dynamic form behavior.
 *
 * Design: each dynamic section (Equipment, Prerequisites, Officials, Events) keeps its
 * own in-memory array of row objects (mirroring Streamlit's session_state pattern).
 * - render<Section>() fully rebuilds that section's rows from its state array.
 *   Called only on page load, and after Add/Delete -- NOT on every keystroke.
 * - Plain typing/selecting is handled by event delegation on the container, which writes
 *   straight into the state array without touching the DOM (the input already shows what
 *   the user typed) -- this keeps things fast even with 100+ rows (e.g. equipment lists).
 * - On submit, each section's state array is JSON-serialized into a hidden <input>, which
 *   Django's view reads with request.POST.get(...).
 */

(function () {
    "use strict";

    // ---------------------------------------------------------------------
    // Load initial state + option lists rendered by Django via json_script
    // ---------------------------------------------------------------------
    function readJson(id) {
        const el = document.getElementById(id);
        return el ? JSON.parse(el.textContent) : null;
    }

    const PLACEHOLDER = readJson("opt-placeholder");
    const STANDARD_CATEGORIES = readJson("opt-standard-categories") || [];
    const PREREQUISITE_TYPES = readJson("opt-prerequisite-types") || [];
    const PREREQUISITE_STATUSES = readJson("opt-prerequisite-statuses") || [];
    const EVENT_STATUSES = readJson("opt-event-statuses") || [];
    const ADD_PROJECT_URL = readJson("add-project-url");

    let equipmentRows = readJson("initial-equipment") || [];
    let prereqRows = readJson("initial-prereqs") || [];
    let officialRows = readJson("initial-officials") || [];
    let eventRows = readJson("initial-events") || [];

    // ---------------------------------------------------------------------
    // Small DOM-building helpers (build via DOM API, not innerHTML, so field
    // values -- which come from real project data -- never need HTML-escaping)
    // ---------------------------------------------------------------------
    function el(tag, attrs) {
        const node = document.createElement(tag);
        attrs = attrs || {};
        for (const key in attrs) {
            if (key === "class") node.className = attrs[key];
            else if (key === "text") node.textContent = attrs[key];
            else node.setAttribute(key, attrs[key]);
        }
        return node;
    }

    function fieldWrap(labelText, inputEl) {
        const wrap = el("div", { class: "field" });
        wrap.appendChild(el("label", { text: labelText }));
        wrap.appendChild(inputEl);
        return wrap;
    }

    function textInput(value, dataIndex, dataField, extraAttrs) {
        const attrs = Object.assign({ type: "text", "data-index": dataIndex, "data-field": dataField }, extraAttrs || {});
        const input = el("input", attrs);
        input.value = value || "";
        return input;
    }

    function numberInput(value, dataIndex, dataField, min, max) {
        const attrs = { type: "number", min: min != null ? min : 1, "data-index": dataIndex, "data-field": dataField };
        if (max != null) attrs.max = max;
        const input = el("input", attrs);
        input.value = value != null ? value : (min != null ? min : 1);
        return input;
    }

    function dateInput(value, dataIndex, dataField) {
        const input = el("input", { type: "date", "data-index": dataIndex, "data-field": dataField });
        input.value = value || "";
        return input;
    }

    function selectInput(options, selectedValue, dataIndex, dataField, includePlaceholder) {
        const select = el("select", { "data-index": dataIndex, "data-field": dataField });
        const allOptions = includePlaceholder ? [PLACEHOLDER].concat(options) : options;
        allOptions.forEach(function (opt) {
            const optionEl = el("option", { value: opt, text: opt });
            if (opt === selectedValue) optionEl.setAttribute("selected", "selected");
            select.appendChild(optionEl);
        });
        return select;
    }

    function deleteButton(label, dataIndex, extraClass) {
        return el("button", {
            type: "button",
            class: "btn btn-danger btn-small " + (extraClass || ""),
            "data-index": dataIndex,
            text: label,
        });
    }

    // ---------------------------------------------------------------------
    // SECTION: Equipment Specifications
    // ---------------------------------------------------------------------
    const equipmentContainer = document.getElementById("equipment-container");

    function renderEquipment() {
        equipmentContainer.innerHTML = "";
        equipmentRows.forEach(function (row, idx) {
            equipmentContainer.appendChild(buildEquipmentRow(row, idx));
        });
    }

    function buildEquipmentRow(row, idx) {
        const block = el("div", { class: "row-block", "data-row-index": idx });
        block.appendChild(el("div", { class: "row-block-title", text: "Equipment Entity #" + (idx + 1) }));

        const grid = el("div", { class: "row-grid", style: "grid-template-columns: 2fr 2fr 1fr;" });

        // Category select + optional custom-category text field
        const catWrap = el("div", { class: "field" });
        catWrap.appendChild(el("label", { text: "Equipment Category #" + (idx + 1) + ":" }));
        const catOptions = STANDARD_CATEGORIES.concat(["Other (Custom)"]);
        const catSelect = selectInput(catOptions, row.category_sel, idx, "category_sel", true);
        catSelect.classList.add("eq-category-select");
        catWrap.appendChild(catSelect);

        const customWrap = el("div", { class: "field", style: row.category_sel === "Other (Custom)" ? "margin-top:8px;" : "margin-top:8px; display:none;" });
        customWrap.classList.add("eq-custom-category-wrap");
        customWrap.appendChild(el("label", { text: "Enter Custom Category #" + (idx + 1) + ":" }));
        customWrap.appendChild(textInput(row.category_custom, idx, "category_custom"));
        catWrap.appendChild(customWrap);

        grid.appendChild(catWrap);
        grid.appendChild(fieldWrap("Tag Number / Name #" + (idx + 1) + ":", textInput(row.tag, idx, "tag")));
        grid.appendChild(fieldWrap("Quantity #" + (idx + 1) + ":", numberInput(row.count, idx, "count", 1)));

        block.appendChild(grid);

        // Parameters sub-list
        const paramsSection = el("div", { class: "section-block" });
        paramsSection.appendChild(el("label", { text: "Parameters:" }));
        const paramsContainer = el("div", { class: "params-container", "data-index": idx });
        (row.params || []).forEach(function (param, pIdx) {
            paramsContainer.appendChild(buildParamRow(param, idx, pIdx));
        });
        paramsSection.appendChild(paramsContainer);

        const addParamBtn = el("button", {
            type: "button", class: "btn btn-small add-param-btn", "data-index": idx,
            text: "Add Parameter to Equipment #" + (idx + 1),
        });
        paramsSection.appendChild(addParamBtn);
        block.appendChild(paramsSection);

        if (equipmentRows.length > 1) {
            const delBtn = deleteButton("Delete Equipment #" + (idx + 1), idx, "delete-equipment-btn");
            delBtn.style.marginTop = "12px";
            block.appendChild(delBtn);
        }

        return block;
    }

    function buildParamRow(param, rowIdx, pIdx) {
        const row = el("div", { class: "param-row", "data-param-index": pIdx });
        row.appendChild(textInput(param.label, rowIdx, "label", { placeholder: "Parameter Label", "data-param-index": pIdx }));
        row.appendChild(textInput(param.val, rowIdx, "val", { placeholder: "Parameter Value", "data-param-index": pIdx }));
        if ((equipmentRows[rowIdx].params || []).length > 1) {
            const delBtn = el("button", {
                type: "button", class: "btn btn-small delete-param-btn",
                "data-index": rowIdx, "data-param-index": pIdx, text: "Delete",
            });
            row.appendChild(delBtn);
        } else {
            row.appendChild(el("div"));
        }
        return row;
    }

    function renderParams(rowIdx) {
        const container = equipmentContainer.querySelector('.params-container[data-index="' + rowIdx + '"]');
        if (!container) return;
        container.innerHTML = "";
        (equipmentRows[rowIdx].params || []).forEach(function (param, pIdx) {
            container.appendChild(buildParamRow(param, rowIdx, pIdx));
        });
    }

    equipmentContainer.addEventListener("input", function (e) {
        const idx = e.target.getAttribute("data-index");
        const field = e.target.getAttribute("data-field");
        if (idx === null || !field) return;
        const pIdx = e.target.getAttribute("data-param-index");
        if (pIdx !== null) {
            equipmentRows[idx].params[pIdx][field] = e.target.value;
        } else {
            equipmentRows[idx][field] = e.target.value;
        }
    });

    equipmentContainer.addEventListener("change", function (e) {
        if (!e.target.classList.contains("eq-category-select")) return;
        const idx = e.target.getAttribute("data-index");
        equipmentRows[idx].category_sel = e.target.value;
        const block = e.target.closest(".row-block");
        const wrap = block.querySelector(".eq-custom-category-wrap");
        wrap.style.display = e.target.value === "Other (Custom)" ? "block" : "none";
    });

    equipmentContainer.addEventListener("click", function (e) {
        if (e.target.classList.contains("delete-equipment-btn")) {
            const idx = parseInt(e.target.getAttribute("data-index"), 10);
            equipmentRows.splice(idx, 1);
            renderEquipment();
        } else if (e.target.classList.contains("add-param-btn")) {
            const idx = e.target.getAttribute("data-index");
            equipmentRows[idx].params.push({ label: "", val: "" });
            renderParams(idx);
        } else if (e.target.classList.contains("delete-param-btn")) {
            const idx = e.target.getAttribute("data-index");
            const pIdx = parseInt(e.target.getAttribute("data-param-index"), 10);
            equipmentRows[idx].params.splice(pIdx, 1);
            renderParams(idx);
        }
    });

    document.getElementById("add-equipment-btn").addEventListener("click", function () {
        equipmentRows.push({ category_sel: PLACEHOLDER, category_custom: "", tag: "", count: 1, params: [{ label: "", val: "" }] });
        renderEquipment();
    });

    // ---------------------------------------------------------------------
    // SECTION: Project Prerequisites
    // ---------------------------------------------------------------------
    const prereqsContainer = document.getElementById("prereqs-container");

    function renderPrereqs() {
        prereqsContainer.innerHTML = "";
        prereqRows.forEach(function (row, idx) {
            prereqsContainer.appendChild(buildPrereqRow(row, idx));
        });
    }

    function buildPrereqRow(row, idx) {
        const block = el("div", { class: "row-block", "data-row-index": idx });
        block.appendChild(el("div", { class: "row-block-title", text: "Prerequisite #" + (idx + 1) }));

        const grid = el("div", { class: "row-grid", style: "grid-template-columns: 2fr 2fr 3fr 0.8fr;" });

        const typeWrap = el("div", { class: "field" });
        typeWrap.appendChild(el("label", { text: "Prerequisite Type #" + (idx + 1) + ":" }));
        const typeSelect = selectInput(PREREQUISITE_TYPES, row.type_sel, idx, "type_sel", true);
        typeSelect.classList.add("prereq-type-select");
        typeWrap.appendChild(typeSelect);

        const customWrap = el("div", { class: "field", style: row.type_sel === "Other (Custom)" ? "margin-top:8px;" : "margin-top:8px; display:none;" });
        customWrap.classList.add("prereq-custom-wrap");
        customWrap.appendChild(el("label", { text: "Custom Prerequisite #" + (idx + 1) + ":" }));
        customWrap.appendChild(textInput(row.type_custom, idx, "type_custom"));
        typeWrap.appendChild(customWrap);

        grid.appendChild(typeWrap);
        grid.appendChild(fieldWrap("Status #" + (idx + 1) + ":", selectInput(PREREQUISITE_STATUSES, row.status, idx, "status", false)));
        grid.appendChild(fieldWrap("Remarks #" + (idx + 1) + ":", textInput(row.remarks, idx, "remarks")));

        const actionWrap = el("div", { class: "row-actions" });
        if (prereqRows.length > 1) {
            actionWrap.appendChild(deleteButton("Delete", idx, "delete-prereq-btn"));
        }
        grid.appendChild(actionWrap);

        block.appendChild(grid);
        return block;
    }

    prereqsContainer.addEventListener("input", function (e) {
        const idx = e.target.getAttribute("data-index");
        const field = e.target.getAttribute("data-field");
        if (idx === null || !field) return;
        prereqRows[idx][field] = e.target.value;
    });

    prereqsContainer.addEventListener("change", function (e) {
        if (!e.target.classList.contains("prereq-type-select")) return;
        const idx = e.target.getAttribute("data-index");
        prereqRows[idx].type_sel = e.target.value;
        const block = e.target.closest(".row-block");
        const wrap = block.querySelector(".prereq-custom-wrap");
        wrap.style.display = e.target.value === "Other (Custom)" ? "block" : "none";
    });

    prereqsContainer.addEventListener("click", function (e) {
        if (e.target.classList.contains("delete-prereq-btn")) {
            const idx = parseInt(e.target.getAttribute("data-index"), 10);
            prereqRows.splice(idx, 1);
            renderPrereqs();
        }
    });

    document.getElementById("add-prereq-btn").addEventListener("click", function () {
        prereqRows.push({ type_sel: PLACEHOLDER, type_custom: "", status: PREREQUISITE_STATUSES[0], remarks: "" });
        renderPrereqs();
    });

    // ---------------------------------------------------------------------
    // SECTION: Officials Involved
    // ---------------------------------------------------------------------
    const officialsContainer = document.getElementById("officials-container");

    function renderOfficials() {
        officialsContainer.innerHTML = "";
        officialRows.forEach(function (row, idx) {
            officialsContainer.appendChild(buildOfficialRow(row, idx));
        });
    }

    function buildOfficialRow(row, idx) {
        const block = el("div", { class: "row-block", "data-row-index": idx });
        block.appendChild(el("div", { class: "row-block-title", text: "Official #" + (idx + 1) }));

        const grid = el("div", { class: "row-grid", style: "grid-template-columns: 2fr 2fr 2fr 1.5fr 0.8fr;" });
        grid.appendChild(fieldWrap("Name #" + (idx + 1) + ":", textInput(row.name, idx, "name")));
        grid.appendChild(fieldWrap("Designation #" + (idx + 1) + ":", textInput(row.designation, idx, "designation")));
        grid.appendChild(fieldWrap("Department #" + (idx + 1) + ":", textInput(row.department, idx, "department")));
        grid.appendChild(fieldWrap("Employee ID #" + (idx + 1) + ":", textInput(row.employee_id, idx, "employee_id")));

        const actionWrap = el("div", { class: "row-actions" });
        if (officialRows.length > 1) {
            actionWrap.appendChild(deleteButton("Delete", idx, "delete-official-btn"));
        }
        grid.appendChild(actionWrap);

        block.appendChild(grid);
        return block;
    }

    officialsContainer.addEventListener("input", function (e) {
        const idx = e.target.getAttribute("data-index");
        const field = e.target.getAttribute("data-field");
        if (idx === null || !field) return;
        officialRows[idx][field] = e.target.value;
    });

    officialsContainer.addEventListener("click", function (e) {
        if (e.target.classList.contains("delete-official-btn")) {
            const idx = parseInt(e.target.getAttribute("data-index"), 10);
            officialRows.splice(idx, 1);
            renderOfficials();
        }
    });

    document.getElementById("add-official-btn").addEventListener("click", function () {
        officialRows.push({ name: "", designation: "", department: "", employee_id: "" });
        renderOfficials();
    });

    // ---------------------------------------------------------------------
    // SECTION: Project Major Events (Gantt-style, Duration <-> Start/Finish sync)
    // ---------------------------------------------------------------------
    const eventsContainer = document.getElementById("events-container");

    function renderEvents() {
        eventsContainer.innerHTML = "";
        eventRows.forEach(function (row, idx) {
            eventsContainer.appendChild(buildEventRow(row, idx));
        });
    }

    function buildEventRow(row, idx) {
        const block = el("div", { class: "row-block", "data-row-index": idx });
        block.appendChild(el("div", { class: "row-block-title", text: "Event #" + (idx + 1) }));

        const topGrid = el("div", { class: "row-grid", style: "grid-template-columns: 2.2fr 1.3fr 1.7fr 0.8fr; margin-bottom:12px;" });
        topGrid.appendChild(fieldWrap("Event Name #" + (idx + 1) + ":", textInput(row.event_name, idx, "event_name")));
        topGrid.appendChild(fieldWrap("Status #" + (idx + 1) + ":", selectInput(EVENT_STATUSES, row.status, idx, "status", true)));
        topGrid.appendChild(fieldWrap("Remarks #" + (idx + 1) + ":", textInput(row.remarks, idx, "remarks")));
        const actionWrap = el("div", { class: "row-actions" });
        if (eventRows.length > 1) {
            actionWrap.appendChild(deleteButton("Delete", idx, "delete-event-btn"));
        }
        topGrid.appendChild(actionWrap);
        block.appendChild(topGrid);

        block.appendChild(el("p", { class: "caption", text: "Planned (Duration = expected time for completion)" }));
        const plannedGrid = el("div", { class: "row-grid", style: "grid-template-columns: 1.3fr 1fr 1.3fr; margin-bottom:12px;" });
        plannedGrid.appendChild(fieldWrap("Planned Start #" + (idx + 1) + ":", dateInput(row.planned_start, idx, "planned_start")));
        plannedGrid.appendChild(fieldWrap("Duration (Days) #" + (idx + 1) + ":", numberInput(row.duration, idx, "duration", 1)));
        plannedGrid.appendChild(fieldWrap("Planned Finish #" + (idx + 1) + ":", dateInput(row.planned_finish, idx, "planned_finish")));
        block.appendChild(plannedGrid);

        block.appendChild(el("p", { class: "caption", text: "Actual" }));
        const actualGrid = el("div", { class: "row-grid", style: "grid-template-columns: 1.3fr 1.3fr 1fr;" });
        actualGrid.appendChild(fieldWrap("Actual Start #" + (idx + 1) + ":", dateInput(row.actual_start, idx, "actual_start")));
        actualGrid.appendChild(fieldWrap("Actual Finish #" + (idx + 1) + ":", dateInput(row.actual_finish, idx, "actual_finish")));
        actualGrid.appendChild(fieldWrap("Criticality Rating #" + (idx + 1) + " (1-5):", numberInput(row.criticality_rating, idx, "criticality_rating", 1, 5)));
        block.appendChild(actualGrid);

        // Percent complete drives the actual (current) S-curve. It is only meaningful
        // for work that is underway: Completed always counts as 100 and Planned as 0,
        // so the input is disabled for those statuses to stop the number contradicting
        // the status shown beside it.
        const progressGrid = el("div", { class: "row-grid", style: "grid-template-columns: 1fr 2fr;" });
        const progressInput = numberInput(row.progress_pct != null ? row.progress_pct : 0, idx, "progress_pct", 0, 100);
        if (row.status === "Completed") {
            progressInput.value = 100;
            progressInput.disabled = true;
        } else if (row.status === "Planned" || row.status === PLACEHOLDER) {
            progressInput.value = 0;
            progressInput.disabled = true;
        }
        progressGrid.appendChild(fieldWrap("Percent Complete #" + (idx + 1) + " (0-100):", progressInput));
        const hint = el("div", { class: "field" });
        hint.appendChild(el("label", { text: "\u00A0" }));
        hint.appendChild(el("p", { class: "caption",
            text: "Used for the current S-curve. Editable once the activity is In Progress or Delayed." }));
        progressGrid.appendChild(hint);
        block.appendChild(progressGrid);

        return block;
    }

    // ---- Date helpers (UTC-based to avoid local-timezone off-by-one bugs) ----
    function parseDateUTC(dateStr) {
        if (!dateStr) return null;
        const parts = dateStr.split("-").map(Number);
        if (parts.length !== 3 || !parts[0] || !parts[1] || !parts[2]) return null;
        return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    }

    function formatDateUTC(dateObj) {
        const y = dateObj.getUTCFullYear();
        const m = String(dateObj.getUTCMonth() + 1).padStart(2, "0");
        const d = String(dateObj.getUTCDate()).padStart(2, "0");
        return y + "-" + m + "-" + d;
    }

    function addDaysToDateString(dateStr, days) {
        const dt = parseDateUTC(dateStr);
        if (!dt) return dateStr;
        dt.setUTCDate(dt.getUTCDate() + days);
        return formatDateUTC(dt);
    }

    function daysBetweenDateStrings(startStr, finishStr) {
        const start = parseDateUTC(startStr);
        const finish = parseDateUTC(finishStr);
        if (!start || !finish) return 0;
        return Math.round((finish - start) / (1000 * 60 * 60 * 24));
    }

    function syncEventPlannedFinish(rowBlock, idx) {
        const startInput = rowBlock.querySelector('[data-field="planned_start"]');
        const durationInput = rowBlock.querySelector('[data-field="duration"]');
        const finishInput = rowBlock.querySelector('[data-field="planned_finish"]');
        const startVal = startInput.value;
        const durationVal = parseInt(durationInput.value, 10) || 1;
        if (!startVal) return;
        const newFinish = addDaysToDateString(startVal, durationVal - 1);
        finishInput.value = newFinish;
        eventRows[idx].planned_start = startVal;
        eventRows[idx].duration = durationVal;
        eventRows[idx].planned_finish = newFinish;
    }

    function syncEventDuration(rowBlock, idx) {
        const startInput = rowBlock.querySelector('[data-field="planned_start"]');
        const durationInput = rowBlock.querySelector('[data-field="duration"]');
        const finishInput = rowBlock.querySelector('[data-field="planned_finish"]');
        const startVal = startInput.value;
        const finishVal = finishInput.value;
        if (!startVal || !finishVal) return;
        const newDuration = Math.max(daysBetweenDateStrings(startVal, finishVal) + 1, 1);
        durationInput.value = newDuration;
        eventRows[idx].planned_start = startVal;
        eventRows[idx].planned_finish = finishVal;
        eventRows[idx].duration = newDuration;
    }

    eventsContainer.addEventListener("input", function (e) {
        const idx = e.target.getAttribute("data-index");
        const field = e.target.getAttribute("data-field");
        if (idx === null || !field) return;
        eventRows[idx][field] = e.target.value;
    });

    eventsContainer.addEventListener("change", function (e) {
        const idx = e.target.getAttribute("data-index");
        const field = e.target.getAttribute("data-field");
        if (idx === null || !field) return;
        eventRows[idx][field] = e.target.value;

        const rowBlock = e.target.closest(".row-block");
        if (field === "planned_start" || field === "duration") {
            syncEventPlannedFinish(rowBlock, idx);
        } else if (field === "planned_finish") {
            syncEventDuration(rowBlock, idx);
        } else if (field === "status") {
            // Changing status changes whether Percent Complete is editable, and forces
            // it to 100 or 0 for terminal statuses. Re-render this section so the input
            // state always matches the status the user just picked.
            if (e.target.value === "Completed") {
                eventRows[idx].progress_pct = 100;
            } else if (e.target.value === "Planned" || e.target.value === PLACEHOLDER) {
                eventRows[idx].progress_pct = 0;
            }
            renderEvents();
        }
    });

    eventsContainer.addEventListener("click", function (e) {
        if (e.target.classList.contains("delete-event-btn")) {
            const idx = parseInt(e.target.getAttribute("data-index"), 10);
            eventRows.splice(idx, 1);
            renderEvents();
        }
    });

    document.getElementById("add-event-btn").addEventListener("click", function () {
        eventRows.push({
            event_name: "", planned_start: "", planned_finish: "", duration: 1,
            actual_start: "", actual_finish: "", criticality_rating: 1,
            status: PLACEHOLDER, progress_pct: 0, remarks: "",
        });
        renderEvents();
    });

    // ---------------------------------------------------------------------
    // SECTION: Statutory Approvals (fixed matrix, server-rendered rows --
    // just wire up the date-field enable/disable behavior here)
    // ---------------------------------------------------------------------
    const APPROVAL_DATE_ENABLED_STATUSES = ["Available", "Pending"];

    document.querySelectorAll(".approval-status-select").forEach(function (select) {
        select.addEventListener("change", function () {
            const row = select.closest(".approval-grid-row");
            const dateInputEl = row.querySelector(".approval-date-input");
            if (APPROVAL_DATE_ENABLED_STATUSES.indexOf(select.value) !== -1) {
                dateInputEl.removeAttribute("readonly");
            } else {
                dateInputEl.value = "";
                dateInputEl.setAttribute("readonly", "readonly");
            }
        });
    });

    // ---------------------------------------------------------------------
    // Submit: package every section's current state into hidden JSON fields
    // ---------------------------------------------------------------------
    document.getElementById("project-form").addEventListener("submit", function () {
        document.getElementById("equipment_json").value = JSON.stringify(equipmentRows);
        document.getElementById("prereqs_json").value = JSON.stringify(prereqRows);
        document.getElementById("officials_json").value = JSON.stringify(officialRows);
        document.getElementById("events_json").value = JSON.stringify(eventRows);

        const approvalsData = {};
        document.querySelectorAll(".approval-grid-row").forEach(function (row) {
            const type = row.getAttribute("data-approval-type");
            const status = row.querySelector(".approval-status-select").value;
            const date = row.querySelector(".approval-date-input").value;
            approvalsData[type] = { status: status, date: date };
        });
        document.getElementById("approvals_json").value = JSON.stringify(approvalsData);
    });

    // ---------------------------------------------------------------------
    // Delete Draft: confirm, then reload a blank "Add New Project" form
    // ---------------------------------------------------------------------
    document.getElementById("delete-draft-btn").addEventListener("click", function () {
        if (confirm("Discard this draft? All unsaved entries will be lost.")) {
            window.location.href = ADD_PROJECT_URL;
        }
    });

    // ---------------------------------------------------------------------
    // Initial render
    // ---------------------------------------------------------------------
    renderEquipment();
    renderPrereqs();
    renderOfficials();
    renderEvents();
})();
