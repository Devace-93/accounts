import { component$, useSignal, type Signal } from "@builder.io/qwik";
import { tr, useI18n } from "../i18n";

interface Props {
  id: string;
  label: string;
  value: Signal<string>;
  /** data-testid of the input (the toggle button is always `toggle-password`). */
  testId?: string;
  autoComplete?: "current-password" | "new-password";
  minLength?: number;
  required?: boolean;
  hint?: string;
  error?: string;
  onBlur$?: () => void;
}

/**
 * Password input with an eye / eye-off toggle. Used for every password on the
 * hosted pages (login, signup + confirm, profile current / new + confirm) so
 * they all behave the same. The toggle only flips the input type; the value
 * never leaves the field.
 */
export const PasswordField = component$<Props>(
  ({ id, label, value, testId = "password", autoComplete = "current-password", minLength, required = true, hint, error, onBlur$ }) => {
    const i18n = useI18n();
    const shown = useSignal(false);
    const toggleLabel = shown.value ? tr(i18n, "auth.hidePassword") : tr(i18n, "auth.showPassword");
    return (
      <div data-password-field>
        <label class="label" for={id}>
          {label}
        </label>
        <div class="relative">
          <input
            id={id}
            type={shown.value ? "text" : "password"}
            required={required}
            minLength={minLength}
            autoComplete={autoComplete}
            class={["input pe-11", error ? "border-red-400 focus:border-red-500 focus:ring-red-500" : ""]}
            data-testid={testId}
            aria-invalid={error ? "true" : undefined}
            aria-describedby={hint || error ? `${id}-hint` : undefined}
            value={value.value}
            onInput$={(_, el) => (value.value = el.value)}
            onBlur$={onBlur$}
          />
          <button
            type="button"
            class="absolute inset-y-0 end-0 flex w-10 items-center justify-center text-slate-400 hover:text-slate-600 focus:outline-none focus:text-primary-600"
            aria-label={toggleLabel}
            title={toggleLabel}
            aria-pressed={shown.value}
            aria-controls={id}
            data-testid="toggle-password"
            onClick$={() => (shown.value = !shown.value)}
          >
            {shown.value ? (
              /* eye-off */
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                <path d="M1 1l22 22" />
              </svg>
            ) : (
              /* eye */
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            )}
          </button>
        </div>
        {error ? (
          <p id={`${id}-hint`} class="mt-1 text-xs text-red-600" role="alert">
            {error}
          </p>
        ) : hint ? (
          <p id={`${id}-hint`} class="mt-1 text-xs text-slate-400">
            {hint}
          </p>
        ) : null}
      </div>
    );
  },
);
