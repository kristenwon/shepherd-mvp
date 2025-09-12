'use client';
import Image from "next/image";
import Link from "next/link";

export default function Header() {
    return (
        <div className="w-full h-20 bg-[#0C0C0C] flex items-center justify-between px-20 border-b border-[#353535]">
            <div className="flex flex-row pl-6 gap-x-3">
                <Link href="/">
                    <Image
                        src="/shepherd-name.png"
                        height={70}
                        width={140}
                        alt="Shepherd Logo"
                    />
                </Link>
            </div>
            <div className="flex flex-row space-x-2 items-center">
                <Image
                    src="/images/pfp.png"
                    height={30}
                    width={30}
                    alt="Profile Picture"
                />
                <div className="flex flex-col">
                    <p className="text-sm">PT</p>
                    <p className="text-[#8f8f8f] text-sm">@0xps</p>
                </div>
            </div>
        </div>
    )
}