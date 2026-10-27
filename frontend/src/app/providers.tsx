import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui";
import { AppearanceProvider, useAppearance } from "./appearance";
import { DemoProvider } from "./demo-store";

function ThemedToaster() {
  const { resolvedTheme } = useAppearance();
  return <Toaster theme={resolvedTheme} position="bottom-right" richColors closeButton toastOptions={{ className: "font-sans" }} />;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } } }));
  return (
    <QueryClientProvider client={client}>
      <AppearanceProvider>
        <DemoProvider>
          <TooltipProvider delayDuration={250}>
            {children}
            <ThemedToaster />
          </TooltipProvider>
        </DemoProvider>
      </AppearanceProvider>
    </QueryClientProvider>
  );
}
