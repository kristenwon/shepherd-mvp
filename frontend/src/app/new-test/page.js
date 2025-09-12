"use client";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import References from "@/components/References";
import ModalWrapper from "@/components/ModalWrapper";
import { useState } from "react";

export default function NewTest() {
    const [showRef, setShowRef] = useState(false);
    const [selectedReference, setSelectedReference] = useState(null);
    const [attachedReference, setAttachedReference] = useState(null);
    const [selectedEnv, setSelectedEnv] = useState(null);
    const [repoUrl, setRepoUrl] = useState("");
    const router = useRouter();

    const handleAttach = () => {
        if(selectedReference) {
            setAttachedReference(selectedReference);
            setShowRef(false);
        }
    }

    return (
        <div className="bg-black h-full flex flex-col py-8 px-24 space-y-8">
            <div className="flex flex-col space-y-4">
                <div className="w-full flex flex-row justify-between items-center">
                    <div className="flex flex-col">
                        <p className="text-md font-semibold">Repository URL</p>
                        <p className="text-[#8f8f8f]">Insert the repository link you&apos;d like to explore</p>
                    </div>
                </div>
                <select
                    className="w-full p-4 border border-[#232323] rounded-md bg-[#0C0C0C] text-[#e5e7eb]"
                    value={repoUrl}
                    onChange={(e) => setRepoUrl(e.target.value)}
                    >
                    <option value="" disabled>Choose repository…</option>
                    <option value="https://github.com/dhruvjain2905/naive-receiver">
                        https://github.com/dhruvjain2905/naive-receiver
                    </option>
                    <option value="https://github.com/dhruvjain2905/Truster">
                        https://github.com/dhruvjain2905/Truster
                    </option>
                </select>

            </div>
            <div className="flex flex-col space-y-4">
                <div className="flex flex-col">
                    <p className="text-md font-semibold">Project description</p>
                    <p className="text-[#8f8f8f]">Please provide the protocol documentation to help better inform the repository.</p>
                </div>
                <textarea
                    type="text"
                    className="w-full p-4 h-36 border border-[#232323] rounded-md bg-[#0C0C0C] text-[#595959] placeholder-[#595959] placeholder:italic"
                    placeholder="Insert documentation..."
                />
                <div className="w-fit flex flex-row items-center justify-center px-4 py-2 space-x-2 rounded-lg bg-[#DF153E]">
                    <Image
                        src="/images/she.png"
                        height={20}
                        width={20}
                        alt="Upload"
                    />
                    <p className="text-sm font-semibold">Upload White Paper</p>
                </div>
            </div>
            <div className="flex flex-col space-y-4">
                <div className="flex flex-col">
                    <p className="text-md font-semibold">Attach Reference</p>
                    <p className="text-[#8f8f8f]">Attach related contracts you&apos;ve ref to inform vulnerability exploration.</p>
                </div>
                {attachedReference ? (
                    <div className="w-fit flex flex-row px-4 py-2 rounded-lg space-x-2 items-center bg-[#0C0C0C] border border-[#232323]">
                        <Image
                            src="/images/defi.png"
                            width={35}
                            height={35}
                            alt="DeFiHackLabs"
                        />
                        <Image
                            src="/images/file.png"
                            width={20}
                            height={20}
                            alt="File"
                        />
                        <p className="text-sm">{selectedReference}</p>
                        <button onClick={() => setAttachedReference(null)}>
                            <Image
                                src="/images/x.png"
                                alt="Close"
                                width={16}
                                height={16}
                            />
                        </button>
                    </div>
                ) : (
                        <button className="w-fit flex flex-row items-center justify-center px-4 py-1 space-x-2 rounded-lg bg-[#232323]" onClick={() => setShowRef(true)}>
                            <p className="text-lg text-[#595959]">+</p>
                            <p className="text-sm font-semibold text-[#595959]">Attach Files</p>
                        </button>
                )}
            </div>
            <div className="flex flex-col space-y-4">
                <div className="w-full flex flex-row justify-between items-center">
                    <div className="flex flex-col">
                        <p className="text-md font-semibold">Select an Environment</p>
                        <p className="text-[#8f8f8f]">Please select the environment where you&apos;d like to deploy the smart contracts from the repository indicated.</p>
                    </div>
                </div>
                <div className="flex flex-row justify-between items-center">
                    <div className="flex flex-row space-x-2">
                        <button
                            className={`px-5 py-3 rounded-lg border border-[#232323] ${
                                selectedEnv === "local" ? "bg-[#df153e]" : "bg-[#0C0C0C]"
                            }`}
                            onClick={() => setSelectedEnv(selectedEnv === "local" ? null : "local")}
                        >
                            Local
                        </button>
                        <button
                            onClick={() => setSelectedEnv(selectedEnv === "testnet" ? null : "testnet")}
                            className={`px-5 py-3 rounded-lg border border-[#232323] ${
                                selectedEnv === "testnet" ? "bg-[#232323]" : "bg-[#232323]"
                            }`}
                        >
                            <p className="text-sm font-semibold text-[#595959]">Testnet</p>
                        </button>
                    </div>
                    <button
                        className="bg-[#df153e] px-6 py-3 rounded-lg hover:scale-105"
                        onClick={() => {
                            if (repoUrl.trim()) {
                            router.push(`/mas-run?repoUrl=${encodeURIComponent(repoUrl)}`);
                            } else {
                            alert("Please enter a repository URL.");
                            }
                        }}
                    >
                        Next
                    </button>
                </div>
            </div>
            {showRef && (
                <ModalWrapper>
                    <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50">
                        <div className="relative flex flex-col px-8 py-4 bg-[#0C0C0C] border border-[#232323] space-y-4 rounded-lg w-full max-w-lg">
                            <button
                                onClick={() => setShowRef(false)}
                                className="absolute top-4 right-4"
                            >
                                <Image
                                src="/images/x.png"
                                alt="Close"
                                width={16}
                                height={16}
                                />
                            </button>

                            <div className="flex flex-col space-y-1">
                                <p className="text-md font-semibold">References</p>
                                <p className="text-[#8f8f8f]">Identify smart contracts with similar vulnerabilities to support your hypothesis.</p>
                            </div>

                            <References
                                clicked={selectedReference}
                                setClicked={setSelectedReference}
                            />

                            <button
                                className="bg-[#df153e] w-fit flex flex-row items-center justify-center px-4 py-2 space-x-2 rounded-lg text-sm"
                                onClick={handleAttach}
                            >
                                Attach
                            </button>
                        </div>
                    </div>
                    </ModalWrapper>

            )}
        </div>
    );
};