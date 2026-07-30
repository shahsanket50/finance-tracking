import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Finance Tracker",
  description: "Personal finance tracking and CA-style health view",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
