import discord
from discord.ext import commands
from discord import app_commands
import math

class Distribute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="분배", description="보스 수익금을 분배합니다. (MVP 3% 수수료 자동 차감)")
    @app_commands.describe(
        amount="판매된 총 금액 (수수료 3%는 봇이 자동 차감합니다)", 
        people="파티 인원 수", 
        percents="(선택) 차등 분배 시 퍼센트를 띄어쓰기나 쉼표로 입력 (예: 30 30 40)"
    )
    async def split_meso(self, interaction: discord.Interaction, amount: int, people: int, percents: str = None):
        
        # 무조건 3% 경매장 수수료 차감
        actual_amount = math.floor(amount * 0.97)
        fee_text = " *(MVP 3% 수수료 차감)*"

        # 퍼센트 옵션이 없을 때 (기본 1/N 균등 분배)
        if not percents:
            per_person = actual_amount // people
            await interaction.response.send_message(f"💰 판매 금액: **{amount:,}** 메소\n💸 실제 정산 금액: **{actual_amount:,}** 메소{fee_text}\n👉 **{people}명 균등 분배 1인당: {per_person:,} 메소**")
            
        # 퍼센트 옵션이 있을 때 (차등 분배)
        else:
            try:
                cleaned_str = percents.replace(",", " ")
                percent_list = [float(p.strip()) for p in cleaned_str.split() if p.strip()]
                
                if len(percent_list) != people:
                    return await interaction.response.send_message(
                        f"⚠️ 인원수({people}명)와 입력한 퍼센트의 개수({len(percent_list)}개)가 일치하지 않습니다!", 
                        ephemeral=True
                    )
                
                total_percent = sum(percent_list)
                if not (99.9 <= total_percent <= 100.1): 
                    return await interaction.response.send_message(
                        f"⚠️ 입력한 퍼센트의 합이 100%가 아닙니다! (현재 합: {total_percent}%)\n비율을 다시 확인해주세요.", 
                        ephemeral=True
                    )
                
                result_text = f"💰 판매 금액: **{amount:,}** 메소\n💸 실제 정산 금액: **{actual_amount:,}** 메소{fee_text}\n\n"
                
                percent_counts = {}
                for p in percent_list:
                    percent_counts[p] = percent_counts.get(p, 0) + 1
                    
                for p, count in sorted(percent_counts.items(), reverse=True):
                    person_cut = int(actual_amount * (p / 100))
                    display_p = int(p) if p.is_integer() else p
                    result_text += f"🔹 **{display_p}% ({count}명):** 인당 **{person_cut:,}** 메소\n"
                    
                await interaction.response.send_message(result_text)
                
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ 퍼센트는 숫자로만 입력해주세요. (예: 30 30 40 또는 30,30,40)", 
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Distribute(bot))