import { getReport } from "@/lib/report";
import { AppHeader } from "@/components/AppHeader";
import { Dashboard } from "@/components/Dashboard";

export default function Home() {
  const report = getReport();

  return (
    <>
      <AppHeader meta={report.meta} />
      <Dashboard report={report} />
    </>
  );
}
