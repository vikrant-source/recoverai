import React from 'react';
import { Header } from './Header';

interface LayoutProps {
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children }) => (
  <div className="min-h-screen bg-navy-950 text-gray-100">
    <Header />
    <main className="max-w-screen-2xl mx-auto px-6 py-8">{children}</main>
  </div>
);
