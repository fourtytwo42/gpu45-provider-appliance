"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, Gauge, KeyRound } from "lucide-react";
import { cn } from "@/lib/cn";

const destinations = [
  { href: "/models", label: "Library", icon: BookOpen },
  { href: "/benchmarks", label: "Benchmarks", icon: Gauge },
  { href: "/keys", label: "API Access", icon: KeyRound },
];

export function ModelsWorkspaceNav() {
  const pathname = usePathname();
  return <nav aria-label="Models workspace" className="flex gap-1 overflow-x-auto border-b border-[#223044]">
    {destinations.map((destination) => {
      const Icon = destination.icon;
      const active = pathname === destination.href || pathname.startsWith(`${destination.href}/`);
      return <Link
        key={destination.href}
        href={destination.href}
        aria-current={active ? "page" : undefined}
        className={cn(
          "inline-flex h-11 shrink-0 items-center gap-2 border-b-2 px-3 text-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#21d4fd]",
          active ? "border-[#21d4fd] text-white" : "border-transparent text-[#8a98aa] hover:text-white",
        )}
      >
        <Icon className={cn("h-4 w-4", active ? "text-[#21d4fd]" : "text-[#617083]")} />
        {destination.label}
      </Link>;
    })}
  </nav>;
}
