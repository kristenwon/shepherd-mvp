"use client";
import Link from "next/link";
import Repositories from "@/components/Repositories";
import References from "@/components/References";
import { useEffect, useState, useCallback } from "react";

export default function Home() {
  const [showModal, setShowModal] = useState(false);

  // show on first client render
  useEffect(() => {
    setShowModal(true);
  }, []);

  // close on Esc
  const onKeyDown = useCallback((e) => {
    if (e.key === "Escape") setShowModal(false);
  }, []);
  useEffect(() => {
    if (!showModal) return;
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showModal, onKeyDown]);

  return (
    <div className="bg-black h-full flex flex-col py-8 px-24 space-y-6">
      <div className="flex flex-col space-y-6">
        <div className="w-full flex flex-row justify-between items-center">
          <div className="flex flex-col">
            <p className="text-md font-semibold">My Repositories</p>
            <p className="text-[#8f8f8f]">Access all your previous repositories and hypotheses.</p>
          </div>
          <Link href="/new-test">
            <button className="bg-[#df153e] px-4 py-2 rounded-lg hover:scale-105">+</button>
          </Link>
        </div>
        <div className="bg-[#0C0C0C] p-6 border border-[#232323] rounded-lg">
          <Repositories />
        </div>
      </div>

      <div className="flex flex-col space-y-6">
        <div className="w-full flex flex-row justify-between items-center">
          <div className="flex flex-col">
            <p className="text-md font-semibold">References</p>
            <p className="text-[#8f8f8f]">Identify smart contracts with similar vulnerabilities to support your hypothesis.</p>
          </div>
          <button className="bg-[#df153e] px-4 py-2 rounded-lg hover:scale-105">+</button>
        </div>
        <div className="bg-[#0C0C0C] p-6 border border-[#232323] rounded-lg">
          <References />
        </div>
      </div>

      {/* Modal */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShowModal(false)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="relative w-full max-w-lg rounded-xl border border-[#232323] bg-[#0C0C0C] p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="space-y-3">
              <p className="text-sm text-gray-200">
                <span className="text-[#df153e]">
                  Shepherd is an AI-driven security engine that validates and reproduces smart contract exploits.
                </span>{" "}
                Our goal is to give auditors and developers a security copilot that automates setup, execution, and proof of vulnerabilities that normally take hours of manual work.
              </p>
              <p className="text-sm text-gray-200">
                <span className="text-[#df153e]">
                  Shepherd Alpha
                </span>{" "}
                is a guided demo of that system. In this release, Shepherd:
              </p>
              <ul className="list-disc text-sm text-gray-200 pl-6">
                <li>
                  Spins up an environment for smart contract repos with clean deployment pipelines (e.g., Damn Vulnerable DeFi, NFT/token examples)
                </li>
                <li>
                  Orchestrates attack paths based on known exploit classes
                </li>
                <li>
                  Produces reproducible exploit transcripts auditors can use as PoCs
                </li>
              </ul>
              <p className="text-sm text-gray-200">
                Auditors today rely on slow manual processes or static tools that can flag issues but can’t execute them end-to-end. Shepherd shows that multi-agent AI can—spinning up the environment, chaining the calls, and proving the exploit in full.
              </p>
              <p className="text-sm text-gray-200">
                Right now, Alpha runs on repos with straightforward initialization. Complex protocols like Uniswap or Compound—where deployment and state setup are heavier—remain the focus of our upcoming Beta, which generalizes Shepherd’s orchestration to production-grade protocols.
              </p>
            </div>

            <div className="mt-6 flex justify-center items-center gap-3">
              <button
                className="px-4 py-2 rounded-md border border-[#232323] hover:bg-white/5"
                onClick={() => setShowModal(false)}
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
