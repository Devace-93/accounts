import { component$, Slot } from "@builder.io/qwik";
import { useLocation } from "@builder.io/qwik-city";
import { Logo } from "../../components/logo";
import { Footer } from "../../components/footer";
import { LanguagePicker } from "../../components/language-picker";
import { ThemeToggle } from "../../components/theme-toggle";

/**
 * Centered card layout for every hosted page (login, signup, magic, verify,
 * profile, logout): logo + language / theme controls on top, the shared 3m4
 * footer below. The profile page gets a wider column.
 */
export default component$(() => {
  const loc = useLocation();
  const wide = loc.url.pathname.startsWith("/profile");
  return (
    <div class="flex min-h-screen flex-col bg-slate-50">
      <header class="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-5">
        <Logo />
        <div class="flex items-center gap-1">
          <LanguagePicker />
          <ThemeToggle />
        </div>
      </header>
      <main class="flex flex-1 items-start justify-center px-4 py-10 sm:items-center">
        <div class={["w-full", wide ? "max-w-2xl" : "max-w-md"]}>
          <Slot />
        </div>
      </main>
      <Footer />
    </div>
  );
});
