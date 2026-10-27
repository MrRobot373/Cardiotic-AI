import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui";
import { LoginPage } from "@/features/auth/LoginPage";
import { RouteError } from "./RouteError";

const Worklist = lazy(() => import("@/features/worklist/WorklistPage"));
const EcgReview = lazy(() => import("@/features/review/EcgReviewPage"));
const Report = lazy(() => import("@/features/reports/ReportPage"));
const Reports = lazy(() => import("@/features/reports/ReportsPage"));
const Patients = lazy(() => import("@/features/patients/PatientsPage"));
const Patient = lazy(() => import("@/features/patients/PatientPage"));
const Holters = lazy(() => import("@/features/holter/HolterListPage"));
const Holter = lazy(() => import("@/features/holter/HolterReviewPage"));
const Monitoring = lazy(() => import("@/features/monitoring/MonitoringPage"));
const Upload = lazy(() => import("@/features/upload/UploadPage"));
const Ai = lazy(() => import("@/features/ai/AiPage"));
const Audit = lazy(() => import("@/features/audit/AuditPage"));
const Settings = lazy(() => import("@/features/settings/SettingsPage"));

const page = (el: ReactNode) => <Suspense fallback={<div className="flex h-64 items-center justify-center"><Spinner className="size-5" /></div>}>{el}</Suspense>;

export const router = createBrowserRouter(
  [
    { path: "/login", element: <LoginPage />, errorElement: <RouteError /> },
    { path: "/ecg/:id/report", element: page(<Report />), errorElement: <RouteError /> },
    {
      path: "/",
      element: <AppShell />,
      errorElement: <RouteError />,
      children: [
        { index: true, element: page(<Worklist />) },
        { path: "ecg/:id", element: page(<EcgReview />) },
        { path: "patients", element: page(<Patients />) },
        { path: "patients/:id", element: page(<Patient />) },
        { path: "holter", element: page(<Holters />) },
        { path: "holter/:id", element: page(<Holter />) },
        { path: "monitoring", element: page(<Monitoring />) },
        { path: "reports", element: page(<Reports />) },
        { path: "upload", element: page(<Upload />) },
        { path: "ai", element: page(<Ai />) },
        { path: "audit", element: page(<Audit />) },
        { path: "settings/:section?", element: page(<Settings />) },
      ],
    },
  ],
  { basename: import.meta.env.BASE_URL.replace(/\/$/, "") || "/" },
);
