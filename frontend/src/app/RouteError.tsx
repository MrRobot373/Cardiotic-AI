import { isRouteErrorResponse, Link, useRouteError } from "react-router";
import { Button } from "@/components/ui";

export function RouteError() {
  const err = useRouteError();
  const notFound = isRouteErrorResponse(err) && err.status === 404;
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
      <h1 className="text-xl font-semibold">{notFound ? "Page not found" : "Something went wrong"}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{notFound ? "This address does not exist in the demo." : String((err as Error)?.message ?? err)}</p>
      <Button asChild variant="strong"><Link to="/">Back to the worklist</Link></Button>
    </div>
  );
}
