/* Lab Mango Django Admin quick-pick date & time widget.
   Zero external dependencies; formats presets in Django's configured TIME_ZONE. */
(function () {
  'use strict';

  function formatPartsInTz(date, timeZone) {
    const formatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    });
    const parts = {};
    for (const part of formatter.formatToParts(date)) {
      parts[part.type] = part.value;
    }
    return {
      dateStr: `${parts.year}-${parts.month}-${parts.day}`,
      timeStr: `${parts.hour}:${parts.minute}`,
      hour: Number(parts.hour),
      minute: Number(parts.minute),
    };
  }

  function formatDisplayDate(dateStr, timeStr) {
    const [year, month, day] = dateStr.split('-').map(Number);
    const [hour, minute] = timeStr.split(':').map(Number);
    if (!year || !month || !day || Number.isNaN(hour) || Number.isNaN(minute)) return '';
    const ref = new Date(Date.UTC(year, month - 1, day, 12, 0));
    const weekdayMonthDay = new Intl.DateTimeFormat('en-US', {
      timeZone: 'UTC',
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    }).format(ref);
    const hh = String(hour).padStart(2, '0');
    const mm = String(minute).padStart(2, '0');
    return `${weekdayMonthDay} at ${hh}:${mm}`;
  }

  function diffMinutesFromNowInTz(dateStr, timeStr, timeZone) {
    const nowParts = formatPartsInTz(new Date(), timeZone);
    const [ny, nm, nd] = nowParts.dateStr.split('-').map(Number);
    const [sy, sm, sd] = dateStr.split('-').map(Number);
    const [sh, smin] = timeStr.split(':').map(Number);
    const nowUtcWall = Date.UTC(ny, nm - 1, nd, nowParts.hour, nowParts.minute);
    const selUtcWall = Date.UTC(sy, sm - 1, sd, sh, smin);
    return Math.round((selUtcWall - nowUtcWall) / 60000);
  }

  function formatDuration(minutes) {
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const remMin = minutes % 60;
    if (hours < 24) {
      return remMin >= 10 ? `${hours}h ${remMin}m` : `${hours} ${hours === 1 ? 'hour' : 'hours'}`;
    }
    const days = Math.floor(hours / 24);
    const remHours = hours % 24;
    if (remHours >= 2) return `${days}d ${remHours}h`;
    return `${days} ${days === 1 ? 'day' : 'days'}`;
  }

  function initWidget(root) {
    const timeZone = root.dataset.timezone || 'UTC';
    const allowClear = root.dataset.allowClear === 'true';
    const dateInput = root.querySelector('input[type="date"]');
    const timeInput = root.querySelector('input[type="time"]');
    const preview = root.querySelector('[data-lm-dtp-preview]');
    const chips = Array.from(root.querySelectorAll('.lm-dtp__chip'));
    const todayChip = root.querySelector('[data-lm-dtp-today]');

    if (!dateInput || !timeInput) return;

    // Keep "Today 18:00" useful even in the evening by switching to "End of today (23:59)".
    function refreshTodayChip() {
      if (!todayChip) return;
      const nowParts = formatPartsInTz(new Date(), timeZone);
      if (nowParts.hour >= 18) {
        todayChip.dataset.preset = 'today:23:59';
        todayChip.textContent = 'End of today (23:59)';
      } else {
        todayChip.dataset.preset = 'today:18:00';
        todayChip.textContent = 'Today 18:00';
      }
    }

    function updatePreview() {
      if (!preview) return;
      preview.classList.remove('is-warning');
      const d = dateInput.value;
      const t = timeInput.value;
      if (!d && !t) {
        preview.textContent = allowClear
          ? `Leave blank to use default 7-day history retention (${timeZone}).`
          : `Pick a preset above or choose a date & time (${timeZone}).`;
        return;
      }
      if (!d || !t) {
        preview.textContent = 'Select both date and time.';
        return;
      }
      const mins = diffMinutesFromNowInTz(d, t, timeZone);
      const formatted = formatDisplayDate(d, t);
      if (mins <= 0) {
        preview.classList.add('is-warning');
        preview.textContent = `Selected time is in the past (${formatted}, ${timeZone}).`;
      } else {
        preview.textContent = `Expires in ~${formatDuration(mins)} · ${formatted} (${timeZone})`;
      }
    }

    function clearActiveChips() {
      chips.forEach((chip) => chip.classList.remove('is-active'));
    }

    function applyPreset(preset, activeButton) {
      if (preset === 'clear') {
        dateInput.value = '';
        timeInput.value = '';
        clearActiveChips();
        updatePreview();
        return;
      }

      const now = new Date();
      let targetDateStr = '';
      let targetTimeStr = '';

      if (preset.startsWith('hours:')) {
        const hours = Number(preset.split(':')[1]);
        const target = new Date(now.getTime() + hours * 3600 * 1000);
        // Round to the nearest 5 minutes for cleaner expiry timestamps.
        const rounded = new Date(Math.ceil(target.getTime() / 300000) * 300000);
        const parts = formatPartsInTz(rounded, timeZone);
        targetDateStr = parts.dateStr;
        targetTimeStr = parts.timeStr;
      } else if (preset.startsWith('days:')) {
        const days = Number(preset.split(':')[1]);
        const target = new Date(now.getTime() + days * 24 * 3600 * 1000);
        const rounded = new Date(Math.ceil(target.getTime() / 300000) * 300000);
        const parts = formatPartsInTz(rounded, timeZone);
        targetDateStr = parts.dateStr;
        targetTimeStr = parts.timeStr;
      } else if (preset.startsWith('today:')) {
        const parts = formatPartsInTz(now, timeZone);
        targetDateStr = parts.dateStr;
        targetTimeStr = preset.slice('today:'.length);
      } else if (preset.startsWith('tomorrow:')) {
        const tomorrow = new Date(now.getTime() + 24 * 3600 * 1000);
        const parts = formatPartsInTz(tomorrow, timeZone);
        targetDateStr = parts.dateStr;
        targetTimeStr = preset.slice('tomorrow:'.length);
      }

      if (targetDateStr && targetTimeStr) {
        dateInput.value = targetDateStr;
        timeInput.value = targetTimeStr;
        clearActiveChips();
        if (activeButton && activeButton.classList.contains('lm-dtp__chip')) {
          activeButton.classList.add('is-active');
        }
        dateInput.dispatchEvent(new Event('change', { bubbles: true }));
        timeInput.dispatchEvent(new Event('change', { bubbles: true }));
        updatePreview();
      }
    }

    // Open the native calendar / clock popover when clicking anywhere inside the input.
    [dateInput, timeInput].forEach((input) => {
      input.addEventListener('click', () => {
        if (typeof input.showPicker === 'function') {
          try {
            input.showPicker();
          } catch {
            // Ignore when browser requires a different gesture or picker is already open.
          }
        }
      });
      input.addEventListener('input', () => {
        clearActiveChips();
        updatePreview();
      });
      input.addEventListener('change', () => {
        updatePreview();
      });
    });

    root.querySelectorAll('[data-preset]').forEach((btn) => {
      btn.addEventListener('click', () => {
        refreshTodayChip();
        applyPreset(btn.dataset.preset || '', btn);
      });
    });

    // Set a helpful min date attribute (today in server timezone).
    const todayParts = formatPartsInTz(new Date(), timeZone);
    if (!dateInput.value) {
      dateInput.min = todayParts.dateStr;
    }

    refreshTodayChip();
    updatePreview();
  }

  function initAll() {
    document.querySelectorAll('[data-lm-dtp]').forEach(initWidget);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
