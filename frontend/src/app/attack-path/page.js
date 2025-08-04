import AttackPathGraph from '@/components/AttackPathGraph';

export default function AttackPathPage() {
  return (
    <div className="bg-black min-h-screen flex flex-col py-8 px-24 space-y-6">
      <div className="flex flex-col space-y-6">
        <div className="w-full flex flex-row justify-between items-center">
          <div className="flex flex-col">
            <h1 className="text-2xl font-bold text-white">Attack Path Visualization</h1>
            <p className="text-[#595959]">Interactive visualization of the NaiveReceiver exploit attack path</p>
          </div>
        </div>
        
        <div className="bg-[#0C0C0C] p-6 border border-[#232323] rounded-lg">
          <AttackPathGraph />
        </div>
        
        <div className="bg-[#0C0C0C] p-6 border border-[#232323] rounded-lg">
          <h2 className="text-lg font-semibold text-white mb-4">Attack Steps Explanation</h2>
          <div className="space-y-3 text-sm text-gray-300">
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">1</span>
              <p><strong>Initial Balance Check:</strong> Check WETH balances for player, FlashLoanReceiver, and NaiveReceiverPool</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">2</span>
              <p><strong>Build Batch FlashLoan Calls:</strong> Create 10 identical flashLoan calls with 0 amount</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">3</span>
              <p><strong>Wrap in Multicall:</strong> Bundle the 10 flashLoan calls into a single multicall transaction</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">4</span>
              <p><strong>Build Meta-Transaction:</strong> Package the multicall payload into an EIP-712 meta-transaction</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">5</span>
              <p><strong>Sign Meta-Transaction:</strong> Sign the meta-transaction with the attacker's private key</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">6</span>
              <p><strong>Execute Meta-Transaction:</strong> Send the signed meta-transaction via BasicForwarder</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">7</span>
              <p><strong>Check Balances Post FlashLoan:</strong> Verify WETH balance changes after flashLoan calls</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">8</span>
              <p><strong>Calculate Total WETH:</strong> Sum WETH balances of pool and receiver for withdrawal</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">9</span>
              <p><strong>Build Withdraw Payload:</strong> Create custom withdraw payload with deployer address suffix</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">10</span>
              <p><strong>Wrap Withdraw in Multicall:</strong> Bundle withdraw payload into multicall transaction</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">11</span>
              <p><strong>Build Withdraw MetaTx:</strong> Package withdraw multicall into meta-transaction</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">12</span>
              <p><strong>Sign Withdraw MetaTx:</strong> Sign the withdraw meta-transaction</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">13</span>
              <p><strong>Execute Withdraw MetaTx:</strong> Execute the signed withdraw meta-transaction</p>
            </div>
            <div className="flex items-start space-x-3">
              <span className="bg-[#df153e] text-white px-2 py-1 rounded text-xs font-bold">14</span>
              <p><strong>Final Balance Check:</strong> Verify final WETH balances after the exploit</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
} 