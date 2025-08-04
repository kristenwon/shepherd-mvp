import Link from "next/link";
import Repositories from "@/components/Repositories";
import References from "@/components/References";

export default function Home() {
  return (
    <div className="bg-black h-full flex flex-col py-8 px-24 space-y-6">
      <div className="flex flex-col space-y-6">
        <div className="w-full flex flex-row justify-between items-center">
            <div className="flex flex-col">
              <p className="text-md font-semibold">My Repositories</p>
              <p className="text-[#595959]">Access all your previous repositories and hypotheses.</p>
            </div>
            <div className="flex space-x-2">
              <Link href="/attack-path">
                <button className="bg-[#4169E1] px-4 py-2 rounded-lg hover:scale-105 text-white">Attack Path</button>
              </Link>
              <Link href="/new-test">
                <button className="bg-[#df153e] px-4 py-2 rounded-lg hover:scale-105">+</button>
              </Link>
            </div>
        </div>
        <div className="bg-[#0C0C0C] p-6 border border-[#232323] rounded-lg">
          <Repositories />
        </div>
      </div>
      <div className="flex flex-col space-y-6">
        <div className="w-full flex flex-row justify-between items-center">
            <div className="flex flex-col">
              <p className="text-md font-semibold">References</p>
              <p className="text-[#595959]">Identify smart contracts with similar vulnerabilities to support your hypothesis.</p>
            </div>
              <button className="bg-[#df153e] px-4 py-2 rounded-lg hover:scale-105">+</button>
        </div>
        <div className="bg-[#0C0C0C] p-6 border border-[#232323] rounded-lg">
          <References />
        </div>
      </div>
    </div>
  );
}
