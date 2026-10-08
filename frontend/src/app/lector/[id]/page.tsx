import ReaderView from "@/components/ReaderView";

export default function LectorPage({ params }: { params: { id: string } }) {
  return <ReaderView docId={params.id} />;
}
