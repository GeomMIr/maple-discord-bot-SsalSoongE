import discord
from discord.ext import commands
from discord import app_commands
import math

class Distribute(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="분배", description="보스 수익금을 분배합니다. (올려야 할 잡템 가격 계산 포함)")
    @app_commands.describe(
        amount="정산 대상 총 금액 (인벤토리에 들어온 순수익 기준)", 
        people="파티 인원 수", 
        percents="(선택) 차등 분배 시 퍼센트를 띄어쓰기나 쉼표로 입력 (예: 40 35 25)"
    )
    async def split_meso(self, interaction: discord.Interaction, amount: int, people: int, percents: str = None):
        
        # 퍼센트 옵션이 없을 때 (기본 1/N 균등 분배)[cite: 2]
        if not percents:
            per_person = amount // people
            # 경매장 수수료 3%를 떼고도 per_person을 받기 위해 올려야 하는 가격 (올림 처리)
            list_price = math.ceil(per_person / 0.97)
            
            result_text = f"📥 **분배 금액 (실수령액)**\n"
            result_text += f"🔹 {people}명 균등: 인당 **{per_person:,}** 메소\n\n"
            
            result_text += f"🏷️ **올려야 하는 잡템 가격 (수수료 포함)**\n"
            result_text += f"🔹 1인당: **{list_price:,}** 메소"
            
            await interaction.response.send_message(result_text)
            
        # 퍼센트 옵션이 있을 때 (차등 분배)[cite: 2]
        else:
            try:
                # 쉼표나 공백으로 구분된 퍼센트 입력 처리[cite: 2]
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
                
                net_text = "📥 **분배 금액 (실수령액)**\n"
                list_text = "🏷️ **올려야 하는 잡템 가격 (수수료 포함)**\n"
                
                # 요청하신 포맷(비율 - 금액)에 맞추어 개별 출력
                for p in percent_list:
                    person_cut = int(amount * (p / 100))
                    list_price = math.ceil(person_cut / 0.97)
                    
                    display_p = int(p) if p.is_integer() else p
                    net_text += f"🔹 {display_p}% - **{person_cut:,}** 메소\n"
                    list_text += f"🔹 {display_p}% - **{list_price:,}** 메소\n"
                    
                result_text = net_text + "\n" + list_text
                    
                await interaction.response.send_message(result_text)
                
            except ValueError:
                await interaction.response.send_message(
                    "⚠️ 퍼센트는 숫자로만 입력해주세요. (예: 40 35 25 또는 40,35,25)", 
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Distribute(bot))