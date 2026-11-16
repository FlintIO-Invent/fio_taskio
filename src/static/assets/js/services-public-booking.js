(function () {
    if (!document.body.classList.contains('mm-services-public-booking')) return;
    const bookingForm = document.querySelector('[data-public-booking-form]');
    const intentField = document.getElementById(bookingForm.dataset.bookingIntentId);
    const bookingSection = document.querySelector('[data-book-now-section]');
    const bookLaterSection = document.querySelector('[data-book-later-section]');
    const wizard = document.querySelector('[data-public-booking-wizard]');
    const wizardTabs = wizard ? Array.from(wizard.querySelectorAll('[data-booking-wizard-tab]')) : [];
    const wizardPanes = wizard ? Array.from(wizard.querySelectorAll('[data-booking-wizard-pane]')) : [];
    const previousStepButton = wizard ? wizard.querySelector('[data-booking-wizard-prev]') : null;
    const nextStepButton = wizard ? wizard.querySelector('[data-booking-wizard-next]') : null;
    const submitStepButton = wizard ? wizard.querySelector('[data-booking-wizard-submit]') : null;
    const serviceField = document.getElementById(bookingForm.dataset.serviceId);
    const clientTypeField = document.getElementById(bookingForm.dataset.clientTypeId);
    const companyNameField = document.getElementById(bookingForm.dataset.companyNameId);
    const companyNameSection = document.querySelector('[data-booking-company-name]');
    const staffField = document.getElementById(bookingForm.dataset.staffMemberId);
    const dateInput = document.getElementById(bookingForm.dataset.preferredDateId);
    const timeInput = document.getElementById(bookingForm.dataset.preferredTimeId);
    const slotDataElement = document.getElementById('public-booking-slot-data');
    const slotData = slotDataElement ? JSON.parse(slotDataElement.textContent || '{}') : {};
    const slotPicker = document.querySelector('[data-slot-picker]');
    const manualDateTime = document.querySelector('[data-manual-date-time]');
    const dateGrid = document.querySelector('[data-slot-date-grid]');
    const timeGrid = document.querySelector('[data-slot-time-grid]');
    const emptyState = document.querySelector('[data-slot-empty]');
    const slotSummary = document.querySelector('[data-slot-summary]');
    const slotRange = document.querySelector('[data-slot-range]');
    const slotStaffLabel = document.querySelector('[data-slot-staff-label]');
    const dateStatus = document.querySelector('[data-slot-date-status]');
    const timeStatus = document.querySelector('[data-slot-time-status]');
    const addressDataElement = document.getElementById('public-booking-address-data');
    const addressData = addressDataElement ? JSON.parse(addressDataElement.textContent || '{}') : {};
    const countryField = document.getElementById(bookingForm.dataset.countryId);
    const streetField = document.getElementById(bookingForm.dataset.streetAddressId);
    const postalField = document.getElementById(bookingForm.dataset.postalCodeId);
    const districtControl = document.querySelector('[data-address-control="district"]');
    const postalHelp = document.querySelector('[data-address-help="postal"]');
    const districtName = bookingForm.dataset.districtName;
    const districtId = bookingForm.dataset.districtId;
    let districtField = document.getElementById(districtId);
    let currentWizardStep = 0;
    let selectedDate = dateInput ? dateInput.value : '';

    function normalizeCountry(value) {
      return String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/&/g, ' and ')
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
    }

    function addressStyleName(country) {
      const normalizedCountry = normalizeCountry(country);
      if ((addressData.netherlandsCountries || []).includes(normalizedCountry)) {
        return 'netherlands';
      }
      if ((addressData.sintMaartenCountries || []).includes(normalizedCountry)) {
        return 'sintMaarten';
      }
      return 'caribbean';
    }

    function setAddressLabel(name, value) {
      const label = document.querySelector(`[data-address-label="${name}"]`);
      if (label && value) {
        label.textContent = value;
      }
    }

    function setPlaceholder(field, value) {
      if (field) {
        field.setAttribute('placeholder', value || '');
      }
    }

    function currentDistrictDisplayValue() {
      if (!districtField) {
        return '';
      }
      if (districtField.tagName === 'SELECT') {
        const selectedOption = districtField.options[districtField.selectedIndex];
        if (!districtField.value) {
          return '';
        }
        return selectedOption ? selectedOption.textContent.trim() : districtField.value;
      }
      return districtField.value || '';
    }

    function buildDistrictControl(style) {
      const currentValue = currentDistrictDisplayValue();
      if (style.districtType === 'select') {
        const select = document.createElement('select');
        select.name = districtName;
        select.id = districtId;
        select.className = 'form-select';
        let hasSelectedValue = false;

        (addressData.districtChoices || []).forEach((choice) => {
          const option = document.createElement('option');
          option.value = choice.value;
          option.textContent = choice.label;
          if (currentValue && (choice.value === currentValue || choice.label === currentValue)) {
            option.selected = true;
            hasSelectedValue = true;
          }
          select.appendChild(option);
        });

        if (currentValue && !hasSelectedValue) {
          const option = document.createElement('option');
          option.value = currentValue;
          option.textContent = currentValue;
          option.selected = true;
          select.appendChild(option);
        }

        return select;
      }

      const input = document.createElement('input');
      input.type = 'text';
      input.name = districtName;
      input.id = districtId;
      input.maxLength = 100;
      input.className = 'form-control';
      input.placeholder = style.districtPlaceholder || '';
      input.value = currentValue;
      return input;
    }

    function applyAddressStyle() {
      const styles = addressData.styles || {};
      const style = styles[addressStyleName(countryField ? countryField.value : '')] || styles.caribbean || {};
      setAddressLabel('street', style.streetLabel);
      setAddressLabel('district', style.districtLabel);
      setAddressLabel('postal', style.postalLabel);
      setPlaceholder(streetField, style.streetPlaceholder);
      setPlaceholder(postalField, style.postalPlaceholder);

      if (districtControl) {
        districtField = buildDistrictControl(style);
        districtControl.replaceChildren(districtField);
      }

      if (postalHelp) {
        const postalHelpText = style.postalHelp || '';
        postalHelp.classList.toggle('d-none', !postalHelpText);
        postalHelp.setAttribute('aria-label', postalHelpText);
        postalHelp.setAttribute('data-bs-title', postalHelpText);
        const postalTooltip = window.bootstrap ? window.bootstrap.Tooltip.getInstance(postalHelp) : null;
        if (postalTooltip) {
          postalTooltip.setContent({ '.tooltip-inner': postalHelpText });
        }
      }
    }

    function isBookNowSelected() {
      return intentField ? intentField.value === 'book_now' : false;
    }

    function setStepError(pane, message) {
      const errorTarget = pane ? pane.querySelector('[data-wizard-step-error]') : null;
      if (!errorTarget) {
        return;
      }
      errorTarget.textContent = message || '';
      errorTarget.classList.toggle('d-none', !message);
    }

    function clearFieldState(field) {
      field.classList.remove('is-invalid');
    }

    function controlsForPane(pane) {
      if (!pane) {
        return [];
      }
      return Array.from(pane.querySelectorAll('input, select, textarea')).filter((field) => {
        return (
          !field.disabled &&
          field.type !== 'hidden' &&
          !field.closest('.d-none')
        );
      });
    }

    function validateWizardStep(index) {
      const pane = wizardPanes[index];
      if (!pane) {
        return true;
      }

      setStepError(pane, '');
      let firstInvalidField = null;
      controlsForPane(pane).forEach((field) => {
        clearFieldState(field);
        if (!field.checkValidity()) {
          field.classList.add('is-invalid');
          firstInvalidField = firstInvalidField || field;
        }
      });

      if (index === 1 && isBookNowSelected()) {
        if (!staffField || !staffField.value) {
          if (staffField) {
            staffField.classList.add('is-invalid');
            firstInvalidField = firstInvalidField || staffField;
          }
        } else if (!dateInput || !dateInput.value || !timeInput || !timeInput.value) {
          firstInvalidField = firstInvalidField || staffField;
          setStepError(pane, 'Choose an available day and time before continuing.');
          return false;
        }
      }

      if (firstInvalidField) {
        setStepError(pane, 'Complete the highlighted fields before continuing.');
        firstInvalidField.focus({ preventScroll: false });
        return false;
      }

      return true;
    }

    function activateWizardStep(index) {
      if (!wizardTabs.length || !wizardPanes.length) {
        return;
      }

      currentWizardStep = Math.max(0, Math.min(index, wizardTabs.length - 1));
      wizardTabs.forEach((tab, tabIndex) => {
        const isActive = tabIndex === currentWizardStep;
        tab.classList.toggle('active', isActive);
        tab.classList.toggle('done', tabIndex < currentWizardStep);
        tab.classList.toggle('complete', tabIndex < currentWizardStep - 1);
        tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
        tab.setAttribute('tabindex', isActive ? '0' : '-1');
        tab.id = `booking-step-tab-${tabIndex}`;
        wizardPanes[tabIndex].setAttribute('aria-labelledby', tab.id);
      });
      wizardPanes.forEach((pane, paneIndex) => {
        pane.classList.toggle('active', paneIndex === currentWizardStep);
        pane.classList.toggle('show', paneIndex === currentWizardStep);
      });

      if (currentWizardStep === 3) renderReview();
      if (previousStepButton) {
        previousStepButton.disabled = currentWizardStep === 0;
      }
      if (nextStepButton) {
        nextStepButton.classList.toggle('d-none', currentWizardStep === wizardTabs.length - 1);
      }
      if (submitStepButton) {
        submitStepButton.classList.toggle('d-none', currentWizardStep !== wizardTabs.length - 1);
      }
    }

    function goToWizardStep(index) {
      if (index > currentWizardStep && !validateWizardStep(currentWizardStep)) {
        return;
      }
      activateWizardStep(index);
      const target = wizardPanes[currentWizardStep];
      target.setAttribute("tabindex", "-1");
      target.focus();
    }

    function firstPaneWithServerErrors() {
      return wizardPanes.findIndex((pane) => {
        return Array.from(pane.querySelectorAll('.text-danger')).some((error) => {
          return error.textContent.trim() && !error.hasAttribute('data-wizard-step-error');
        });
      });
    }

    function validateWizardBeforeSubmit(event) {
      for (let index = 0; index < wizardPanes.length; index += 1) {
        activateWizardStep(index);
        if (!validateWizardStep(index)) {
          event.preventDefault();
          return;
        }
      }
    }

    function parseDate(dateString) {
      const parts = String(dateString || '').split('-').map(Number);
      if (parts.length !== 3 || parts.some(Number.isNaN)) {
        return null;
      }
      return new Date(parts[0], parts[1] - 1, parts[2]);
    }

    function formatDate(date) {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, '0');
      const day = String(date.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    }

    function addDays(date, days) {
      const nextDate = new Date(date);
      nextDate.setDate(nextDate.getDate() + days);
      return nextDate;
    }

    function weekdayIndex(date) {
      return (date.getDay() + 6) % 7;
    }

    function formatDayLabel(date) {
      return new Intl.DateTimeFormat(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      }).format(date);
    }

    function formatTimeLabel(minutes) {
      const hour = Math.floor(minutes / 60);
      const minute = minutes % 60;
      return new Intl.DateTimeFormat(undefined, {
        hour: 'numeric',
        minute: '2-digit',
      }).format(new Date(2000, 0, 1, hour, minute));
    }

    function timeValue(minutes) {
      const hour = String(Math.floor(minutes / 60)).padStart(2, '0');
      const minute = String(minutes % 60).padStart(2, '0');
      return `${hour}:${minute}`;
    }

    function selectedStaffId() {
      return staffField ? staffField.value : '';
    }

    function selectedServiceDuration() {
      const serviceId = serviceField ? serviceField.value : '';
      const service = slotData.services && slotData.services[serviceId];
      return Number((service && service.durationMinutes) || slotData.defaultDurationMinutes || 60);
    }

    function availabilityBlocksForStaff(staffId) {
      const businessBlocks = (slotData.availability && slotData.availability.business) || [];
      const staffBlocks =
        (slotData.availability &&
          slotData.availability.staff &&
          slotData.availability.staff[staffId]) ||
        [];
      if (staffBlocks.length || !businessBlocks.length) {
        return staffBlocks;
      }
      return businessBlocks;
    }

    function conflictsWithAppointment(dateString, startMinutes, endMinutes, staffId) {
      const appointments = (slotData.appointments && slotData.appointments[staffId]) || [];
      return appointments.some((appointment) => {
        return (
          appointment.date === dateString &&
          startMinutes < appointment.endMinutes &&
          endMinutes > appointment.startMinutes
        );
      });
    }

    function slotsForDate(dateString) {
      const staffId = selectedStaffId();
      const serviceId = serviceField ? serviceField.value : '';
      const date = parseDate(dateString);
      if (!staffId || !serviceId || !date) {
        return [];
      }

      const durationMinutes = selectedServiceDuration();
      const day = weekdayIndex(date);
      const blocks = availabilityBlocksForStaff(staffId).filter((block) => block.day === day);
      const earliestStart = slotData.earliestStart || {};
      const step = Number(slotData.slotStepMinutes || 15);
      const slots = [];
      const seen = new Set();

      blocks.forEach((block) => {
        for (
          let startMinutes = block.startMinutes;
          startMinutes + durationMinutes <= block.endMinutes;
          startMinutes += step
        ) {
          const endMinutes = startMinutes + durationMinutes;
          if (dateString === earliestStart.date && startMinutes < earliestStart.minutes) {
            continue;
          }
          if (conflictsWithAppointment(dateString, startMinutes, endMinutes, staffId)) {
            continue;
          }
          const value = timeValue(startMinutes);
          if (!seen.has(value)) {
            seen.add(value);
            slots.push({
              value,
              startMinutes,
              label: formatTimeLabel(startMinutes),
            });
          }
        }
      });

      return slots.sort((a, b) => a.startMinutes - b.startMinutes);
    }

    function setEmptyState(message) {
      if (!emptyState) {
        return;
      }
      emptyState.textContent = message || '';
      emptyState.classList.toggle('d-none', !message);
    }

    function renderTimeSlots() {
      if (!timeGrid) {
        return;
      }
      timeGrid.innerHTML = '';
      if (!selectedDate) {
        if (timeStatus) {
          timeStatus.textContent = '';
        }
        return;
      }

      const slots = slotsForDate(selectedDate);
      if (timeStatus) {
        timeStatus.textContent = slots.length ? `${slots.length} open` : 'No openings';
      }
      slots.forEach((slot) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm booking-slot-button';
        const isSelected = dateInput.value === selectedDate && timeInput.value === slot.value;
        button.classList.add(isSelected ? 'btn-primary' : 'btn-phoenix-secondary');
        button.textContent = slot.label;
        button.setAttribute("aria-pressed", String(isSelected));
        button.addEventListener('click', () => {
          dateInput.value = selectedDate;
          timeInput.value = slot.value;
          renderTimeSlots();
          Array.from(timeGrid.children).find(el => el.textContent === slot.label)?.focus();
          if (slotSummary) {
            slotSummary.textContent = `${formatDayLabel(parseDate(selectedDate))} at ${slot.label}`;
          }
        });
        timeGrid.appendChild(button);
      });
    }

    function renderDateSlots() {
      if (!dateGrid || !slotData.dateRange) {
        return;
      }
      dateGrid.innerHTML = '';
      selectedDate = dateInput.value || selectedDate;
      const startDate = parseDate(slotData.dateRange.start);
      const endDate = parseDate(slotData.dateRange.end);
      if (!startDate || !endDate) {
        return;
      }

      let availableDays = 0;
      let firstAvailableDate = '';
      const dateButtons = [];
      for (let date = startDate; date <= endDate; date = addDays(date, 1)) {
        const dateString = formatDate(date);
        const slots = slotsForDate(dateString);
        const hasSlots = slots.length > 0;
        if (hasSlots) {
          availableDays += 1;
          firstAvailableDate = firstAvailableDate || dateString;
        }

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm booking-slot-button';
        button.classList.add(selectedDate === dateString ? 'btn-primary' : 'btn-phoenix-secondary');
        button.disabled = !hasSlots;
        button.setAttribute("aria-pressed", String(selectedDate === dateString));
        button.textContent = formatDayLabel(date);
        button.addEventListener('click', () => {
          selectedDate = dateString;
          dateInput.value = dateString;
          timeInput.value = '';
          renderDateSlots();
          renderTimeSlots();
          Array.from(dateGrid.children).find(el => el.textContent === formatDayLabel(date))?.focus();
          if (slotSummary) {
            slotSummary.textContent = '';
          }
        });
        dateButtons.push({ button, dateString });
        dateGrid.appendChild(button);
      }

      if (!selectedDate || !slotsForDate(selectedDate).length) {
        selectedDate = firstAvailableDate;
      }
      dateButtons.forEach(({ button, dateString }) => {
        button.setAttribute('aria-pressed', String(selectedDate === dateString));
        button.classList.toggle('btn-primary', selectedDate === dateString);
        button.classList.toggle('btn-phoenix-secondary', selectedDate !== dateString);
      });
      if (dateStatus) {
        dateStatus.textContent = availableDays ? `${availableDays} days` : 'No openings';
      }
      setEmptyState(
        availableDays
          ? ''
          : 'No online slots are open for this staff member. You can choose contact before booking instead.'
      );
      renderTimeSlots();
    }

    function renderSlotPicker() {
      if (!slotPicker || !slotData.dateRange) {
        return;
      }
      slotPicker.classList.remove('d-none');
      if (manualDateTime) {
        manualDateTime.classList.add('d-none');
      }
      if (slotRange) {
        slotRange.textContent = `From ${slotData.dateRange.start} through ${slotData.dateRange.end}`;
      }
      if (slotStaffLabel && staffField) {
        const selectedOption = staffField.options[staffField.selectedIndex];
        slotStaffLabel.textContent = selectedOption ? selectedOption.textContent.trim() : '';
        slotStaffLabel.classList.toggle('d-none', !staffField.value);
      }
      if (!selectedStaffId()) {
        if (dateGrid) {
          dateGrid.innerHTML = '';
        }
        if (timeGrid) {
          timeGrid.innerHTML = '';
        }
        if (dateStatus) {
          dateStatus.textContent = '';
        }
        if (timeStatus) {
          timeStatus.textContent = '';
        }
        setEmptyState('Select a staff member to see open appointment slots.');
        return;
      }
      if (!serviceField || !serviceField.value) {
        if (dateGrid) {
          dateGrid.innerHTML = '';
        }
        if (timeGrid) {
          timeGrid.innerHTML = '';
        }
        if (dateStatus) {
          dateStatus.textContent = '';
        }
        if (timeStatus) {
          timeStatus.textContent = '';
        }
        setEmptyState('Select a service to see open appointment slots.');
        return;
      }
      renderDateSlots();
    }

    function syncClientType() {
      if (!clientTypeField || !companyNameField || !companyNameSection) {
        return;
      }
      const isCompany = clientTypeField.value !== 'INDIVIDUAL';
      companyNameSection.classList.toggle('d-none', !isCompany);
      companyNameField.required = isCompany;
      companyNameField.disabled = !isCompany;
      clearFieldState(companyNameField);
      setStepError(wizardPanes[2], '');
    }

    function syncBookingSection() {
      if (!intentField || !bookingSection) {
        return;
      }
      const isBookNow = isBookNowSelected();
      bookingSection.classList.toggle('d-none', !isBookNow);
      if (bookLaterSection) {
        bookLaterSection.classList.toggle('d-none', isBookNow);
      }
      bookingSection.querySelectorAll('select, input').forEach((field) => {
        field.required = isBookNow && !field.matches('[data-slot-value-field]');
        if (!isBookNow) {
          clearFieldState(field);
        }
      });
      if (isBookNow) {
        renderSlotPicker();
      }
    }


    bookingForm.addEventListener("input", () => { if (currentWizardStep === 3) renderReview(); });
    bookingForm.addEventListener("change", () => { if (currentWizardStep === 3) renderReview(); });
    function renderReview() {
      const values = bookingForm.querySelector('[data-booking-review-values]');
      if (!values) return;
      values.replaceChildren();
      const text = name => {
        const field = bookingForm.elements.namedItem(name);
        if (!field) return '';
        return field.tagName === 'SELECT' ? (field.value ? field.selectedOptions[0]?.textContent.trim() || '' : '') : field.value;
      };
      const entries = [
        ['Intent', text('booking_intent')], ['Service', text('service')],
        ['Schedule', isBookNowSelected() ? `${text('preferred_date')} ${text('preferred_time')} · ${bookingForm.dataset.businessZone}` : 'No appointment will be scheduled'],
        ['Staff', isBookNowSelected() ? text('staff_member') : 'Not assigned'],
        ['Contact', `${text('first_name')} ${text('last_name')} · ${text('email')} · ${text('phone')}`],
        ['Company', text('client_type') === 'Individual' ? 'Individual' : text('company_name')],
        ['Location', ['street_address','district','postal_code','country'].map(text).filter(Boolean).join(', ')],
        ['Message', text('message') || 'None'],
      ];
      for (const [label, value] of entries) {
        const dt = document.createElement('dt'); dt.textContent = label;
        const dd = document.createElement('dd'); dd.textContent = value;
        values.append(dt, dd);
      }
    }
    bookingForm.querySelectorAll('[data-booking-review-edit]').forEach(button => button.addEventListener('click', () => goToWizardStep(Number(button.dataset.bookingReviewEdit))));
    wizardTabs.forEach((tab,index) => tab.addEventListener('keydown', event => {
      const delta = {ArrowLeft:-1,ArrowRight:1}[event.key];
      if (!delta) return;
      event.preventDefault();
      goToWizardStep(Math.max(0,Math.min(3,index + (document.documentElement.dir === 'rtl' ? -delta : delta))));
      wizardTabs[currentWizardStep].focus();
    }));
    for (const grid of [dateGrid,timeGrid]) grid?.addEventListener('keydown', event => {
      const delta = {ArrowLeft:-1,ArrowRight:1,ArrowUp:-1,ArrowDown:1}[event.key];
      if (!delta || event.target.tagName !== 'BUTTON') return;
      const buttons = Array.from(grid.querySelectorAll('button:not(:disabled)'));
      const index = buttons.indexOf(event.target);
      event.preventDefault();
      buttons[Math.max(0,Math.min(buttons.length-1,index+delta))]?.focus();
    });
    bookingForm.querySelector('[data-booking-error-summary]')?.addEventListener('click', event => {
      const link = event.target.closest('a[href^="#"]');
      const field = link && document.getElementById(link.hash.slice(1));
      const pane = field?.closest('[data-booking-wizard-pane]');
      if (!pane) return;
      event.preventDefault(); activateWizardStep(wizardPanes.indexOf(pane)); field.focus();
    });

    syncBookingSection();
    syncClientType();
    applyAddressStyle();
    activateWizardStep(Math.max(firstPaneWithServerErrors(), 0));
    if (countryField) {
      countryField.addEventListener('change', applyAddressStyle);
    }
    if (clientTypeField) {
      clientTypeField.addEventListener('change', syncClientType);
    }
    if (intentField) {
      intentField.addEventListener('change', () => {
        syncBookingSection();
        setStepError(wizardPanes[1], '');
      });
    }
    wizardTabs.forEach((tab, index) => {
      tab.addEventListener('click', (event) => {
        event.preventDefault();
        goToWizardStep(index);
      });
    });
    if (previousStepButton) {
      previousStepButton.addEventListener('click', () => {
        activateWizardStep(currentWizardStep - 1);
      });
    }
    if (nextStepButton) {
      nextStepButton.addEventListener('click', () => {
        goToWizardStep(currentWizardStep + 1);
      });
    }
    if (bookingForm) {
      bookingForm.addEventListener('submit', validateWizardBeforeSubmit);
      bookingForm.querySelectorAll('input, select, textarea').forEach((field) => {
        field.addEventListener('input', () => clearFieldState(field));
        field.addEventListener('change', () => clearFieldState(field));
      });
    }
    if (staffField) {
      staffField.addEventListener('change', () => {
        selectedDate = '';
        dateInput.value = '';
        timeInput.value = '';
        if (slotSummary) {
          slotSummary.textContent = '';
        }
        renderSlotPicker();
      });
    }
    if (serviceField) {
      serviceField.addEventListener('change', () => {
        timeInput.value = '';
        if (slotSummary) {
          slotSummary.textContent = '';
        }
        renderSlotPicker();
      });
    }
  })();
